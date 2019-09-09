from abc import ABC, abstractmethod
from typing import Awaitable, Optional

from .state import State
from .typing import TReturn


class ProcessAPI(ABC, Awaitable[TReturn]):
    #
    # State
    #
    @property
    def state(self) -> State:
        ...

    @state.setter
    @abstractmethod
    def state(self, value: State) -> State:
        ...

    @abstractmethod
    async def wait_for_state(self, state: State) -> None:
        ...

    #
    # PID
    #
    @property
    def pid(self) -> int:
        ...

    @pid.setter
    @abstractmethod
    def pid(self, value: int) -> None:
        ...

    @abstractmethod
    async def wait_pid(self) -> int:
        ...

    #
    # Return Value
    #
    @property
    def return_value(self) -> int:
        ...

    @return_value.setter
    @abstractmethod
    def return_value(self, value: int) -> None:
        ...

    @abstractmethod
    async def wait_return_value(self) -> int:
        ...

    #
    # Return Code
    #
    @property
    def returncode(self) -> int:
        ...

    @returncode.setter
    @abstractmethod
    def returncode(self, value: int) -> None:
        ...

    @abstractmethod
    async def wait_returncode(self) -> int:
        ...

    #
    # Error
    #
    @property
    def error(self) -> int:
        ...

    @error.setter
    @abstractmethod
    def error(self, value: int) -> None:
        ...

    @abstractmethod
    async def wait_error(self) -> int:
        ...

    #
    # Result
    #
    @property
    @abstractmethod
    def result(self) -> TReturn:
        ...

    @abstractmethod
    async def wait_result(self) -> TReturn:
        ...

    #
    # Lifecycle management APIs
    #
    @abstractmethod
    async def wait(self) -> None:
        ...

    @abstractmethod
    def poll(self) -> Optional[int]:
        ...

    @abstractmethod
    def kill(self) -> None:
        ...

    @abstractmethod
    def terminate(self) -> None:
        ...

    @abstractmethod
    def send_signal(self, sig: int) -> None:
        ...
