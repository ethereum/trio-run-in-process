class BaseRunInProcessException(Exception):
    pass


class ProcessKilled(BaseRunInProcessException):
    pass


class InvalidState(BaseRunInProcessException):
    pass


class _UnpickleableValue(BaseRunInProcessException):
    """
    Tried to unpickle something that can't.

    Used only internally.
    """


class InvalidDataFromChild(BaseRunInProcessException):
    """
    The child's return value cannot be unpickled.

    This seems to happen only when the child raises a custom exception whose constructor has more
    than one required argument: https://github.com/ethereum/trio-run-in-process/issues/11
    """


class WorkerPoolNotOpen(BaseRunInProcessException):
    pass
