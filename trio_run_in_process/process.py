import os
import signal
from typing import Callable, Optional, Sequence

import trio

from ._utils import pickle_value
from .abc import ProcessAPI
from .exceptions import ProcessKilled
from .state import State
from .typing import TReturn


class Process(ProcessAPI[TReturn]):
    _pid: Optional[int] = None
    _returncode: Optional[int] = None
    _return_value: TReturn
    _error: Optional[BaseException] = None
    _state: State = State.INITIALIZING

    sub_proc_payload: bytes

    def __init__(
        self, async_fn: Callable[..., TReturn], args: Sequence[TReturn]
    ) -> None:
        self._async_fn = async_fn
        self._args = args
        self.sub_proc_payload = pickle_value((self._async_fn, self._args))

        self._has_pid = trio.Event()
        self._has_returncode = trio.Event()
        self._has_return_value = trio.Event()
        self._has_error = trio.Event()
        self._state_changed = trio.Event()

    def __str__(self) -> str:
        return f"Process[{self._async_fn}]"

    #
    # State
    #
    @property
    def state(self) -> State:
        return self._state

    @state.setter
    def state(self, value: State) -> None:
        self._state = value
        self._state_changed.set()
        self._state_changed = trio.Event()

    async def wait_for_state(self, state: State) -> None:
        """
        Block until the process has reached or surpassed the given state.
        """
        if self.state.is_on_or_after(state):
            return

        for _ in range(len(State)):
            await self._state_changed.wait()
            if self.state.is_on_or_after(state):
                break
        else:
            raise BaseException(
                f"This code path should not be reachable since there are a "
                f"finite number of state transitions.  Current state is "
                f"{self.state}"
            )

    #
    # PID
    #
    @property
    def pid(self) -> int:
        if self._pid is None:
            raise AttributeError("No PID set for process")
        return self._pid

    @pid.setter
    def pid(self, value: int) -> None:
        self._pid = value
        self._has_pid.set()

    async def wait_pid(self) -> int:
        await self._has_pid.wait()
        return self.pid

    #
    # Return Value
    #
    @property
    def return_value(self) -> TReturn:
        if not hasattr(self, "_return_value"):
            raise AttributeError("No return_value set")
        return self._return_value

    @return_value.setter
    def return_value(self, value: TReturn) -> None:
        self._return_value = value
        self._has_return_value.set()

    async def wait_return_value(self) -> TReturn:
        await self._has_return_value.wait()
        return self.return_value

    #
    # Return Code
    #
    @property
    def returncode(self) -> int:
        if self._returncode is None:
            raise AttributeError("No returncode set")
        return self._returncode

    @returncode.setter
    def returncode(self, value: int) -> None:
        self._returncode = value
        self._has_returncode.set()

    async def wait_returncode(self) -> int:
        await self._has_returncode.wait()
        return self.returncode

    #
    # Error
    #
    @property
    def error(self) -> Optional[BaseException]:
        if self._error is None and not hasattr(self, "_return_value"):
            raise AttributeError("No error set")
        return self._error

    @error.setter
    def error(self, value: BaseException) -> None:
        self._error = value
        self._has_error.set()

    async def wait_error(self) -> BaseException:
        await self._has_error.wait()
        # mypy is unable to tell that `self.error` **must** be non-null in this
        # case.
        return self.error  # type: ignore

    #
    # Result
    #
    def get_result_or_raise(self) -> TReturn:
        """
        Return the computed result from the process, raising if it was an exception.

        If the process has not finished then raises an `AttributeError`
        """
        if self._error is None and not hasattr(self, "_return_value"):
            raise AttributeError("Process not done")
        elif self._error is not None:
            raise self._error
        elif hasattr(self, "_return_value"):
            return self._return_value
        else:
            raise BaseException("Code path should be unreachable")

    async def wait_result_or_raise(self) -> TReturn:
        """
        Block until the process has exited, either returning the return value
        if execution was successful, or raising an exception if it failed
        """
        await self.wait_returncode()

        if self.returncode == 0:
            return await self.wait_return_value()
        else:
            raise await self.wait_error()

    #
    # Lifecycle management APIs
    #
    async def wait(self) -> None:
        """
        Block until the process has exited.
        """
        await self.wait_returncode()

        if self.returncode == 0:
            await self.wait_return_value()
        else:
            await self.wait_error()

    def poll(self) -> Optional[int]:
        """
        Check if the process has finished.  Returns `None` if the re
        """
        return self.returncode

    def kill(self) -> None:
        self.send_signal(signal.SIGKILL)
        self.status = State.FINISHED
        self.error = ProcessKilled("Process terminated with SIGKILL")

    def terminate(self) -> None:
        self.send_signal(signal.SIGTERM)

    def send_signal(self, sig: int) -> None:
        os.kill(self.pid, sig)
