import os
import signal
from typing import (
    Callable,
    Optional,
    Sequence,
)

import trio

from .abc import ProcessAPI
from .exceptions import ProcessKilled
from .typing import TReturn
from .state import State


class empty:
    pass


class Process(ProcessAPI):
    returncode: Optional[int] = None

    _pid: Optional[int] = None
    _returncode: Optional[int] = None
    _return_value: Optional[TReturn] = empty
    _error: Optional[BaseException] = None
    _state: State = State.INITIALIZING

    def __init__(self, async_fn: Callable[..., TReturn], args: Sequence[TReturn]) -> None:
        self._async_fn = async_fn
        self._args = args

        self._has_pid = trio.Event()
        self._has_returncode = trio.Event()
        self._has_return_value = trio.Event()
        self._has_error = trio.Event()
        self._state_changed = trio.Event()

    def __await__(self) -> TReturn:
        return self.run().__await__()

    #
    # State
    #
    @property
    def state(self) -> State:
        return self._state

    @state.setter
    def state(self, value: State) -> State:
        self._state = value
        self._state_changed.set()
        self._state_changed = trio.Event()

    async def wait_for_state(self, state: State) -> None:
        """
        Block until the process as reached the
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
    def return_value(self) -> int:
        if self._return_value is empty:
            raise AttributeError("No return_value set")
        return self._return_value

    @return_value.setter
    def return_value(self, value: int) -> None:
        self._return_value = value
        self._has_return_value.set()

    async def wait_return_value(self) -> int:
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
    def error(self) -> int:
        if self._error is None and self._return_value is empty:
            raise AttributeError("No error set")
        return self._error

    @error.setter
    def error(self, value: int) -> None:
        self._error = value
        self._has_error.set()

    async def wait_error(self) -> int:
        await self._has_error.wait()
        return self.error

    #
    # Result
    #
    @property
    def result(self) -> TReturn:
        if self._error is None and self._return_value is empty:
            raise AttributeError("Process not done")
        elif self._error is not None:
            raise self._error
        elif self._return_value is not empty:
            return self._return_value
        else:
            raise BaseException("Code path should be unreachable")

    async def wait_result(self) -> TReturn:
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
