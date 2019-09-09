import pytest
import trio

from trio_run_in_process import run_in_process


@pytest.mark.trio
async def test_run_in_process_touch_file(touch_path):
    async def touch_file(path: trio.Path):
        await path.touch()

    with trio.fail_after(2):
        assert not await touch_path.exists()
        await run_in_process(touch_file, touch_path)
        assert await touch_path.exists()


@pytest.mark.trio
async def test_run_in_process_with_result():
    async def return7():
        return 7

    with trio.fail_after(2):
        result = await run_in_process(return7)
    assert result == 7


@pytest.mark.trio
async def test_run_in_process_with_error():
    async def raise_err():
        raise ValueError("Some err")

    with trio.fail_after(2):
        with pytest.raises(ValueError, match="Some err"):
            await run_in_process(raise_err)
