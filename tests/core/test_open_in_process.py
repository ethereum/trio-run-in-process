import pickle
import signal

import pytest
import trio

from trio_run_in_process import ProcessKilled, constants, open_in_process
from trio_run_in_process.exceptions import InvalidDataFromChild
from trio_run_in_process.process import Process
from trio_run_in_process.state import State


@pytest.mark.trio
async def test_open_in_proc_termination_while_running():
    with trio.fail_after(2):
        async with open_in_process(trio.sleep_forever) as proc:
            proc.terminate()
    assert proc.returncode == 15


@pytest.mark.trio
async def test_open_in_proc_kill_while_running():
    with trio.fail_after(2):
        async with open_in_process(trio.sleep_forever) as proc:
            proc.kill()
    assert proc.returncode == -9
    assert isinstance(proc.error, ProcessKilled)


@pytest.mark.trio
async def test_open_proc_interrupt_while_running():
    with trio.fail_after(2):
        async with open_in_process(trio.sleep_forever) as proc:
            proc.send_signal(signal.SIGINT)
        assert proc.returncode == 2


@pytest.mark.trio
async def test_open_proc_invalid_function_call():
    async def takes_no_args():
        pass

    with trio.fail_after(2):
        async with open_in_process(takes_no_args, 1, 2, 3) as proc:
            pass
        assert proc.returncode == 1
        assert isinstance(proc.error, TypeError)


@pytest.mark.trio
async def test_open_proc_unpickleable_params(touch_path):
    async def takes_open_file(f):
        pass

    with trio.fail_after(2):
        with pytest.raises(pickle.PickleError):
            with open(touch_path, "w") as touch_file:
                async with open_in_process(takes_open_file, touch_file):
                    # this code block shouldn't get executed
                    assert False


@pytest.mark.trio
async def test_open_proc_outer_KeyboardInterrupt():
    with trio.fail_after(2):
        with pytest.raises(KeyboardInterrupt):
            async with open_in_process(trio.sleep_forever) as proc:
                raise KeyboardInterrupt
        assert proc.returncode == 2


@pytest.mark.trio
async def test_proc_ignores_KeyboardInterrupt(monkeypatch):
    # If we get a KeyboardInterrupt and the child process does not terminate after being sent a
    # SIGINT, we send a SIGKILL to avoid open_in_process() from hanging indefinitely.
    async def sleep_forever():
        import trio

        while True:
            try:
                await trio.lowlevel.checkpoint()
            except KeyboardInterrupt:
                pass

    monkeypatch.setattr(constants, "SIGINT_TIMEOUT_SECONDS", 0.2)
    with trio.fail_after(constants.SIGINT_TIMEOUT_SECONDS + 1):
        with pytest.raises(KeyboardInterrupt):
            async with open_in_process(sleep_forever) as proc:
                raise KeyboardInterrupt
        assert proc.returncode == -9
        assert isinstance(proc.error, ProcessKilled)


@pytest.mark.trio
async def test_unpickleable_exc():
    sleep = trio.sleep

    # Custom exception classes requiring multiple arguments cannot be pickled:
    # https://bugs.python.org/issue32696
    class CustomException(BaseException):
        def __init__(self, msg, arg2):
            super().__init__(msg)
            self.arg2 = arg2

    async def raise_():
        await sleep(0.01)
        raise CustomException("msg", "arg2")

    with trio.fail_after(2):
        with pytest.raises(InvalidDataFromChild):
            async with open_in_process(raise_) as proc:
                await proc.wait_result_or_raise()


@pytest.mark.trio
async def test_timeout_waiting_for_pid(monkeypatch):
    async def wait_pid(self):
        await trio.sleep(constants.STARTUP_TIMEOUT_SECONDS + 0.1)

    monkeypatch.setattr(Process, "wait_pid", wait_pid)
    monkeypatch.setattr(constants, "STARTUP_TIMEOUT_SECONDS", 1)

    with pytest.raises(trio.TooSlowError):
        async with open_in_process(trio.sleep_forever):
            pass


@pytest.mark.trio
async def test_timeout_waiting_for_executing_state(monkeypatch):
    async def wait_for_state(self, state):
        if state is State.EXECUTING:
            await trio.sleep(constants.STARTUP_TIMEOUT_SECONDS + 0.1)

    monkeypatch.setattr(Process, "wait_for_state", wait_for_state)
    monkeypatch.setattr(constants, "STARTUP_TIMEOUT_SECONDS", 1)

    with pytest.raises(trio.TooSlowError):
        async with open_in_process(trio.sleep_forever):
            pass
