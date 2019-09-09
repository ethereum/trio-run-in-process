import pytest

import trio

from trio_run_in_process import open_in_process, State


@pytest.mark.trio
async def test_Process_object_state_api():
    async def return7():
        return 7

    with trio.fail_after(2):
        async with open_in_process(return7) as proc:
            assert proc.state.is_on_or_after(State.STARTED)

            await proc.wait_for_state(State.FINISHED)
            assert proc.state is State.FINISHED
            assert proc.return_value == 7


@pytest.mark.trio
async def test_Process_object_wait_for_return_value():
    async def return7():
        return 7

    with trio.fail_after(2):
        async with open_in_process(return7) as proc:
            await proc.wait_return_value()
            assert proc.return_value == 7


@pytest.mark.trio
async def test_Process_object_wait_for_pid():
    async def return7():
        return 7

    with trio.fail_after(2):
        async with open_in_process(return7) as proc:
            await proc.wait_pid()
            assert isinstance(proc.pid, int)


@pytest.mark.trio
async def test_Process_object_wait_for_returncode():
    async def system_exit_123():
        raise SystemExit(123)

    with trio.fail_after(2):
        async with open_in_process(system_exit_123) as proc:
            await proc.wait_returncode()
            assert proc.returncode == 123


@pytest.mark.trio
async def test_Process_object_wait_for_error():
    async def raise_error():
        raise ValueError("child-error")

    with trio.fail_after(2):
        async with open_in_process(raise_error) as proc:
            await proc.wait_error()
            assert isinstance(proc.error, ValueError)


@pytest.mark.trio
async def test_Process_object_wait_for_result_when_error():
    async def raise_error():
        raise ValueError("child-error")

    with trio.fail_after(2):
        async with open_in_process(raise_error) as proc:
            with pytest.raises(ValueError, match="child-error"):
                await proc.wait_result()


@pytest.mark.trio
async def test_Process_object_wait_for_result_when_return_value():
    async def return7():
        return 7

    with trio.fail_after(2):
        async with open_in_process(return7) as proc:
            result = await proc.wait_result()
            assert result == 7
            assert proc.error is None


@pytest.mark.trio
async def test_Process_object_wait_when_return_value():
    async def return7():
        return 7

    with trio.fail_after(2):
        async with open_in_process(return7) as proc:
            await proc.wait()
            assert proc.return_value == 7
            assert proc.error is None


@pytest.mark.trio
async def test_Process_object_wait_when_error():
    async def raise_error():
        raise ValueError("child-error")

    with trio.fail_after(2):
        async with open_in_process(raise_error) as proc:
            await proc.wait()
            assert isinstance(proc.error, ValueError)
