# import subprocess
import logging
import os
import signal
from typing import Any, AsyncIterator, Callable

from async_generator import asynccontextmanager
import trio
import trio_typing

from ._utils import (
    coro_read_exactly,
    coro_receive_pickled_value,
    get_subprocess_command,
    pickle_value,
)
from .exceptions import InvalidState
from .process import Process
from .state import State
from .typing import TReturn

logger = logging.getLogger("trio-run-in-process")


async def _monitor_sub_proc(
    proc: Process[TReturn], sub_proc: trio.Process, parent_w: int
) -> None:
    logger.debug("starting subprocess to run %s", proc)
    async with sub_proc:
        # set the process ID
        proc.pid = sub_proc.pid
        logger.debug("subprocess for %s started.  pid=%d", proc, proc.pid)

        # we write the execution data immediately without waiting for the
        # `WAIT_EXEC_DATA` state to ensure that the child process doesn't have
        # to wait for that data due to the round trip times between processes.
        logger.debug("writing execution data for %s over stdin", proc)
        # pass the child process the serialized `async_fn` and `args`
        async with trio.hazmat.FdStream(parent_w) as to_child:
            await to_child.send_all(pickle_value((proc._async_fn, proc._args)))

        # this wait ensures that we
        with trio.fail_after(5):
            await proc.wait_for_state(State.WAIT_EXEC_DATA)

        with trio.fail_after(5):
            await proc.wait_for_state(State.EXECUTING)
        logger.debug("waiting for process %s finish", proc)

    if sub_proc.returncode is None:
        raise Exception("This shouldn't be possible")
    proc.returncode = sub_proc.returncode
    logger.debug("process %s finished: returncode=%d", proc, proc.returncode)


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


async def _monitor_state(
    proc: Process[TReturn], from_child: trio.hazmat.FdStream
) -> None:
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

    result = await coro_receive_pickled_value(from_child)

    # The `returncode` should already be set but we do a quick wait to ensure
    # that it will be set when we access it below.
    with trio.fail_after(5):
        await proc.wait_returncode()

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
) -> AsyncIterator[Process[TReturn]]:
    proc = Process(async_fn, args)

    parent_r, child_w = os.pipe()
    child_r, parent_w = os.pipe()
    parent_pid = os.getpid()

    command = get_subprocess_command(child_r, child_w, parent_pid)

    sub_proc = await trio.open_process(
        command,
        # stdin=subprocess.PIPE,
        # stdout=subprocess.PIPE,
        # stderr=subprocess.PIPE,
        pass_fds=(child_r, child_w),
    )

    async with trio.open_nursery() as nursery:
        nursery.start_soon(_monitor_sub_proc, proc, sub_proc, parent_w)

        async with trio.hazmat.FdStream(parent_r) as from_child:
            with trio.open_signal_receiver(*RELAY_SIGNALS) as signal_aiter:
                # Monitor the child stream for incoming updates to the state of
                # the child process.
                nursery.start_soon(_monitor_state, proc, from_child)

                # Relay any appropriate signals to the child process.
                nursery.start_soon(_relay_signals, proc, signal_aiter)

                await proc.wait_pid()

                # Wait until the child process has reached the STARTED
                # state before yielding the context.  This ensures that any
                # calls to things like `terminate` or `kill` will be handled
                # properly in the child process.
                #
                # The timeout ensures that if something is fundamentally wrong
                # with the subprocess we don't hang indefinitely.
                with trio.fail_after(5):
                    await proc.wait_for_state(State.STARTED)

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

                await proc.wait()

                nursery.cancel_scope.cancel()


@trio_typing.takes_callable_and_args
async def run_in_process(async_fn: Callable[..., TReturn], *args: Any) -> TReturn:
    async with open_in_process(async_fn, *args) as proc:
        await proc.wait()
    return proc.get_result_or_raise()
