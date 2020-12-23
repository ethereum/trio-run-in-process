import pytest
import trio

from trio_run_in_process import open_worker_process


@pytest.mark.trio
async def test_process_result():
    async def return7():
        return 7

    with trio.fail_after(2):
        async with open_worker_process() as worker:
            result = await worker.run(return7)
    assert result == 7


@pytest.mark.trio
async def test_process_error():
    async def raise_err():
        raise ValueError("Some err")

    with trio.fail_after(2):
        with pytest.raises(ValueError, match="Some err"):
            async with open_worker_process() as worker:
                await worker.run(raise_err)


@pytest.mark.trio
async def test_can_do_run_multiple_times():
    async def raise_err():
        raise ValueError("Some err")

    async def return_arg(v):
        return v

    with trio.fail_after(4):
        async with open_worker_process() as worker:
            result = await worker.run(return_arg, 7)
            assert result == 7

            with pytest.raises(ValueError, match="Some err"):
                await worker.run(raise_err)

            result = await worker.run(return_arg, 9)
            assert result == 9


@pytest.mark.trio
async def test_finished_worker_cannot_be_used():
    with trio.fail_after(2):
        async with open_worker_process() as worker:
            await worker.run(trio.sleep, 0)

        with pytest.raises(Exception, match="Worker.* is no longer active"):
            await worker.run(trio.sleep, 0)


@pytest.mark.trio
async def test_reentrance_is_not_allowed():
    with trio.fail_after(2):
        async with open_worker_process() as worker:
            with pytest.raises(Exception, match="Worker.* is busy"):
                async with trio.open_nursery() as nursery:
                    nursery.start_soon(worker.run, trio.sleep, 1)
                    nursery.start_soon(worker.run, trio.sleep, 1)
                    await trio.sleep(0.1)
