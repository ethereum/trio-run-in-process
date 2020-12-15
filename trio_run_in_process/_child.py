import argparse
import os
import signal
import sys
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
    to_parent: trio.hazmat.FdStream,
) -> TReturn:
    with trio.open_signal_receiver(*SHUTDOWN_SIGNALS) as signal_aiter:
        # state: STARTED
        update_state(to_parent, State.STARTED)

        async with trio.open_nursery() as nursery:
            nursery.start_soon(_do_monitor_signals, signal_aiter)

            # state: EXECUTING
            update_state(to_parent, State.EXECUTING)

            result = await async_fn(*args)

            nursery.cancel_scope.cancel()
        return result


def _run_process(parent_pid: int, fd_read: int, fd_write: int) -> None:
    """
    Run the child process
    """
    # state: INITIALIZING
    with os.fdopen(fd_write, "wb", closefd=True) as to_parent:
        # state: INITIALIZED
        update_state(to_parent, State.INITIALIZED)
        with os.fdopen(fd_read, "rb", closefd=True) as from_parent:
            # state: WAIT_EXEC_DATA
            update_state(to_parent, State.WAIT_EXEC_DATA)
            async_fn, args = sync_receive_pickled_value(from_parent)

        # state: BOOTING
        update_state(to_parent, State.BOOTING)

        try:
            try:
                result = trio.run(_do_async_fn, async_fn, args, to_parent)
            except BaseException as err:
                finished_payload = pickle_value(err)
                raise
        except KeyboardInterrupt:
            code = 2
        except SystemExit as err:
            code = err.args[0]
        except BaseException:
            code = 1
        else:
            finished_payload = pickle_value(result)
            code = 0
        finally:
            # state: FINISHED
            update_state_finished(to_parent, finished_payload)
            sys.exit(code)


if __name__ == "__main__":
    args = parser.parse_args()
    _run_process(
        parent_pid=args.parent_pid, fd_read=args.fd_read, fd_write=args.fd_write
    )
