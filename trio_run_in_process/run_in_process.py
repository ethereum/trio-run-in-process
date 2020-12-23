from contextlib import AsyncExitStack
import logging
import os
import signal
from typing import Any, AsyncIterator, Callable
import uuid

from async_generator import asynccontextmanager
import trio
from trio.lowlevel import FdStream
import trio_typing

from . import constants
from ._utils import (
    coro_read_exactly,
    coro_receive_pickled_value,
    get_subprocess_command,
)
from .abc import ProcessAPI, WorkerPoolAPI, WorkerProcessAPI
from .exceptions import (
    InvalidDataFromChild,
    InvalidState,
    WorkerPoolNotOpen,
    _UnpickleableValue,
)
from .process import Process
from .state import State
from .typing import TReturn

logger = logging.getLogger("trio-run-in-process")


async def _relay_signals(
    proc: Process[TReturn], signal_aiter: AsyncIterator[int]
) -> None:
    async for signum in signal_aiter:
        if proc.state.is_before(State.STARTED):
            # If the process has not reached the state where the child process
            # can properly handle the signal, give it a moment to reach the
            # `STARTED` stage.
            with trio.fail_after(1):
                await proc.wait_for_state(State.STARTED)
        logger.debug("relaying signal %s to child process %s", signum, proc)
        proc.send_signal(signum)


async def _monitor_state(proc: Process[TReturn], from_child: FdStream) -> None:
    for current_state in State:
        if proc.state is not current_state:
            raise InvalidState(
                f"Process in state {proc.state} but expected state {current_state}"
            )

        child_state_as_byte = await coro_read_exactly(from_child, 1)

        try:
            child_state = State(child_state_as_byte)
        except TypeError:
            raise InvalidState(f"Child sent state: {child_state_as_byte.hex()}")

        if not proc.state.is_next(child_state):
            raise InvalidState(
                f"Invalid state transition: {proc.state} -> {child_state}"
            )

        if child_state is State.FINISHED:
            # For the FINISHED state we delay updating the state until we also
            # have a return value.
            break

        proc.state = child_state
        logger.debug(
            "Updated process %s state %s -> %s",
            proc,
            current_state.name,
            child_state.name,
        )

    # This is mostly a sanity check but it ensures that the loop variable is
    # what we expect it to be before starting to collect the result the stream.
    if child_state is not State.FINISHED:
        raise InvalidState(f"Invalid final state: {proc.state}")

    logger.debug("Reading process result for %s", proc)
    try:
        proc.returncode, result = await coro_receive_pickled_value(from_child)
    except _UnpickleableValue as e:
        result = InvalidDataFromChild(
            "Unable to unpickle data from child. This may be a custom exception class; see "
            "https://github.com/ethereum/trio-run-in-process/issues/11 for more details. "
            "Original error: %s" % e.args
        )
        result.__cause__ = e
        proc.returncode = 1

    logger.debug(
        "Got result (%s) and returncode (%d) for %s", result, proc.returncode, proc
    )
    if proc.returncode == 0:
        proc.return_value = result
    else:
        proc.error = result

    proc.state = child_state


RELAY_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


@asynccontextmanager
@trio_typing.takes_callable_and_args
async def open_in_process(
    async_fn: Callable[..., TReturn], *args: Any
) -> AsyncIterator[ProcessAPI[TReturn]]:
    async with open_worker_process() as worker:
        async with worker._open(async_fn, *args) as proc:
            yield proc


@trio_typing.takes_callable_and_args
async def run_in_process(async_fn: Callable[..., TReturn], *args: Any) -> TReturn:
    async with open_in_process(async_fn, *args) as proc:
        await proc.wait()
    return proc.get_result_or_raise()


class WorkerProcess(WorkerProcessAPI):
    def __init__(
        self, trio_process: trio.Process, from_child: FdStream, to_child: FdStream,
    ) -> None:
        self._trio_proc = trio_process
        self._from_child = from_child
        self._to_child = to_child
        self._busy = False
        self._dead = False

    @property
    def pid(self) -> int:
        return self._trio_proc.pid

    # This method is private because ProcessAPI methods can be used to kill the child process
    # while the worker is still alive. If this ever needs to be made public we need to ensure the
    # worker is flagged as dead when the child process is terminated.
    @asynccontextmanager
    async def _open(
        self, async_fn: Callable[..., TReturn], *args: Any
    ) -> AsyncIterator[ProcessAPI[TReturn]]:
        if self._dead:
            raise Exception(f"Worker (pid={self.pid}) is no longer active")
        if self._busy:
            raise Exception(f"Worker (pid={self.pid}) is busy")
        self._busy = True
        proc: Process[TReturn] = Process(async_fn, args)
        proc.pid = self._trio_proc.pid
        async with trio.open_nursery() as nursery:
            # We write the execution data immediately without waiting for the
            # `WAIT_EXEC_DATA` state to ensure that the child process doesn't have
            # to wait for that data due to the round trip times between processes.
            logger.debug("Writing execution data for %s over stdin", proc)
            await self._to_child.send_all(proc.sub_proc_payload)

            startup_timeout = int(
                os.getenv(
                    "TRIO_RUN_IN_PROCESS_STARTUP_TIMEOUT",
                    constants.STARTUP_TIMEOUT_SECONDS,
                )
            )
            with trio.open_signal_receiver(*RELAY_SIGNALS) as signal_aiter:
                # Monitor the child stream for incoming updates to the state of
                # the child process.
                nursery.start_soon(_monitor_state, proc, self._from_child)

                # Relay any appropriate signals to the child process.
                nursery.start_soon(_relay_signals, proc, signal_aiter)

                with trio.fail_after(startup_timeout):
                    await proc.wait_pid()

                # Wait until the child process has reached the EXECUTING
                # state before yielding the context.  This ensures that any
                # calls to things like `terminate` or `kill` will be handled
                # properly in the child process.
                #
                # The timeout ensures that if something is fundamentally wrong
                # with the subprocess we don't hang indefinitely.
                with trio.fail_after(startup_timeout):
                    await proc.wait_for_state(State.EXECUTING)

                try:
                    try:
                        yield proc
                    except KeyboardInterrupt as err:
                        # If a keyboard interrupt is encountered relay it to the
                        # child process and then give it a moment to cleanup before
                        # re-raising
                        try:
                            proc.send_signal(signal.SIGINT)
                            with trio.move_on_after(2):
                                await proc.wait()
                        finally:
                            raise err
                finally:
                    await proc.wait()
                    logger.debug(
                        "process %s finished: returncode=%d", proc, proc.returncode
                    )
                    self._busy = False
                    nursery.cancel_scope.cancel()

    async def run(self, async_fn: Callable[..., TReturn], *args: Any) -> TReturn:
        async with self._open(async_fn, *args) as proc:
            return await proc.wait_result_or_raise()


@asynccontextmanager
async def open_worker_process() -> AsyncIterator[WorkerProcessAPI]:
    """
    Open a long-lived process that can be used multiple times to run async functions.

    Concurrent calls to open() or run() are not allowed on the worker, and once the context is
    left, it can no longer be used.
    """
    parent_r, child_w = os.pipe()
    child_r, parent_w = os.pipe()
    parent_pid = os.getpid()
    trio_proc = await trio.open_process(
        get_subprocess_command(child_r, child_w, parent_pid),
        pass_fds=(child_r, child_w),
    )
    try:
        async with trio_proc:
            async with FdStream(parent_r) as from_child, FdStream(parent_w) as to_child:
                worker = WorkerProcess(trio_proc, from_child, to_child)
                yield worker
    finally:
        worker._dead = True


class WorkerPool(WorkerPoolAPI):
    def __init__(self, max_workers: int, id_: uuid.UUID = None) -> None:
        if id_ is None:
            self.id = uuid.uuid4()
        else:
            self.id = id_
        self._max_workers = max_workers
        self._num_workers = 0
        self._send_channel, self._receive_channel = trio.open_memory_channel[
            WorkerProcessAPI
        ](max_workers)
        self._exit_stack = AsyncExitStack()
        self._is_open = False

    def __str__(self) -> str:
        return f"WorkerPool({self.id})"

    @asynccontextmanager
    async def _reserve_worker(self) -> AsyncIterator[WorkerProcessAPI]:
        try:
            worker = self._receive_channel.receive_nowait()
        except trio.WouldBlock:
            if self._num_workers < self._max_workers:
                self._num_workers += 1
                worker = await self._exit_stack.enter_async_context(
                    open_worker_process()
                )
                logger.debug("%s: created new worker: pid=%d", self, worker.pid)
            else:
                logger.debug("%s: waiting for a busy worker to become free", self)
                worker = await self._receive_channel.receive()

        try:
            yield worker
        finally:
            self._send_channel.send_nowait(worker)

    async def run(self, async_fn: Callable[..., TReturn], *args: Any) -> TReturn:
        async with self._reserve_worker() as worker:
            if not self._is_open:
                raise WorkerPoolNotOpen(f"{self} is not open")
            logger.debug(
                "%s: got free worker, running %s with args %s", self, async_fn, args
            )
            return await worker.run(async_fn, *args)

    @asynccontextmanager
    async def _open(self) -> AsyncIterator[WorkerPoolAPI]:
        async with self._exit_stack:
            self._is_open = True
            try:
                yield self
            finally:
                self._is_open = False


@asynccontextmanager
async def open_worker_pool(num_workers: int) -> AsyncIterator[WorkerPoolAPI]:
    """
    Open a pool of long-lived processes that can be used multiple times to run async functions.

    Up to num_workers processes may be created, on demand, and if there are more concurrent calls
    to WorkerPool.run() than num_workers, they will be queued and awaken in order as soon as a
    worker becomes available.
    """
    async with WorkerPool(num_workers)._open() as pool:
        yield pool
