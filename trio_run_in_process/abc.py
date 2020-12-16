from abc import ABC, abstractmethod
from typing import Any, Callable, Generic, Optional

from typing_extensions import AsyncContextManager

from .state import State
from .typing import TReturn


class ProcessAPI(ABC, Generic[TReturn]):
    #
    # State
    #
    @property
    @abstractmethod
    def state(self) -> State:
        ...

    @state.setter
    def state(self, value: State) -> State:
        raise NotImplementedError

    @abstractmethod
    async def wait_for_state(self, state: State) -> None:
        ...

    #
    # PID
    #
    @property
    @abstractmethod
    def pid(self) -> int:
        ...

    @pid.setter
    def pid(self, value: int) -> None:
        raise NotImplementedError

    @abstractmethod
    async def wait_pid(self) -> int:
        ...

    #
    # Return Value
    #
    @property
    @abstractmethod
    def return_value(self) -> TReturn:
        ...

    @return_value.setter
    def return_value(self, value: TReturn) -> None:
        raise NotImplementedError

    @abstractmethod
    async def wait_return_value(self) -> TReturn:
        ...

    #
    # Return Code
    #
    @property
    @abstractmethod
    def returncode(self) -> int:
        ...

    @returncode.setter
    def returncode(self, value: int) -> None:
        raise NotImplementedError

    @abstractmethod
    async def wait_returncode(self) -> int:
        ...

    #
    # Error
    #
    @property
    @abstractmethod
    def error(self) -> Optional[BaseException]:
        ...

    @error.setter
    def error(self, value: BaseException) -> None:
        raise NotImplementedError

    @abstractmethod
    async def wait_error(self) -> Optional[BaseException]:
        ...

    #
    # Result
    #
    @abstractmethod
    def get_result_or_raise(self) -> TReturn:
        ...

    @abstractmethod
    async def wait_result_or_raise(self) -> TReturn:
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


class WorkerProcessAPI(ABC):
    @abstractmethod
    def _open(
        self, async_fn: Callable[..., TReturn], *args: Any
    ) -> AsyncContextManager[ProcessAPI[TReturn]]:
        ...

    @abstractmethod
    async def run(self, async_fn: Callable[..., TReturn], *args: Any) -> TReturn:
        ...
