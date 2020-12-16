import argparse
import io
import os
import signal
from typing import Any, AsyncIterator, Awaitable, BinaryIO, Callable, Sequence

import trio
import trio_typing

from ._utils import pickle_value, sync_receive_pickled_value
from .state import State
from .typing import TReturn

#
# CLI invocation for subprocesses
#
parser = argparse.ArgumentParser(description="trio-run-in-process")
parser.add_argument(
    "--parent-pid", type=int, required=True, help="The PID of the parent process"
)
parser.add_argument(
    "--fd-read",
    type=int,
    required=True,
    help=(
        "The file descriptor that the child process can use to read data that "
        "has been written by the parent process"
    ),
)
parser.add_argument(
    "--fd-write",
    type=int,
    required=True,
    help=(
        "The file descriptor that the child process can use for writing data "
        "meant to be read by the parent process"
    ),
)


def update_state(to_parent: BinaryIO, state: State) -> None:
    to_parent.write(state.value)
    to_parent.flush()


def update_state_finished(to_parent: BinaryIO, finished_payload: bytes) -> None:
    payload = State.FINISHED.value + finished_payload
    to_parent.write(payload)
    to_parent.flush()


SHUTDOWN_SIGNALS = {signal.SIGTERM}


async def _do_monitor_signals(signal_aiter: AsyncIterator[int]) -> None:
    async for signum in signal_aiter:
        raise SystemExit(signum)


@trio_typing.takes_callable_and_args
async def _do_async_fn(
    async_fn: Callable[..., Awaitable[TReturn]],
    args: Sequence[Any],
    to_parent: BinaryIO,
) -> TReturn:
    with trio.open_signal_receiver(*SHUTDOWN_SIGNALS) as signal_aiter:
        update_state(to_parent, State.STARTED)

        async with trio.open_nursery() as nursery:
            nursery.start_soon(_do_monitor_signals, signal_aiter)

            update_state(to_parent, State.EXECUTING)

            result = await async_fn(*args)

            nursery.cancel_scope.cancel()
        return result


def _run_process(
    parent_pid: int, from_parent: io.BytesIO, to_parent: io.BytesIO
) -> None:
    update_state(to_parent, State.WAIT_EXEC_DATA)
    async_fn, args = sync_receive_pickled_value(from_parent)

    update_state(to_parent, State.BOOTING)

    try:
        try:
            result: Any = trio.run(_do_async_fn, async_fn, args, to_parent)
        except BaseException as err:
            result = err
            raise
    except KeyboardInterrupt:
        returncode = 2
    except SystemExit as err:
        returncode = err.args[0]
    except BaseException:
        returncode = 1
    else:
        returncode = 0
    finally:
        finished_payload = pickle_value((returncode, result))
        update_state_finished(to_parent, finished_payload)


if __name__ == "__main__":
    args = parser.parse_args()
    with os.fdopen(args.fd_write, "wb", closefd=True) as to_parent, os.fdopen(
        args.fd_read, "rb", closefd=True
    ) as from_parent:
        while True:
            # When WorkerProcess exits it will close the pipe passed as fd_read here, sending us
            # an EOF and causing a ConnectionError to bubble up here. That's how we know when to
            # terminate.
            try:
                _run_process(args.parent_pid, from_parent, to_parent)
            except ConnectionError:
                break
