import pytest
import trio

from trio_run_in_process import open_worker_pool
from trio_run_in_process.exceptions import WorkerPoolNotOpen


@pytest.mark.trio
async def test_run():
    checkpoint = trio.lowlevel.checkpoint

    async def raise_err():
        await checkpoint()
        raise ValueError("Some err")

    async def return_arg(arg):
        await checkpoint()
        return arg

    with trio.fail_after(2):
        async with open_worker_pool(2) as pool:
            assert 7 == await pool.run(return_arg, 7)
            with pytest.raises(ValueError, match="Some err"):
                await pool.run(raise_err)
            assert 9 == await pool.run(return_arg, 9)


@pytest.mark.trio
async def test_leaving_pool_context_with_pending_tasks():
    # Open a pool with a single worker and schedule two calls to
    # pool.run(trio.sleep_forever), so the second one will sit waiting for a free
    # worker and never actually run. In that case, when we leave the pool context the
    # second run should fail with a WorkerPoolNotOpen exception.

    async def _sleep_forever_on_pool(pool, task_status=trio.TASK_STATUS_IGNORED):
        task_status.started()
        await pool.run(trio.sleep_forever)

    with trio.fail_after(2):
        with pytest.raises(trio.MultiError, match="WorkerPool.* is not open"):
            async with trio.open_nursery() as nursery:
                async with open_worker_pool(1) as pool:
                    await nursery.start(_sleep_forever_on_pool, pool)
                    # Need a relatively long sleep here to ensure the pool creates the worker
                    # process and tells it to run the async function.
                    await trio.sleep(0.2)
                    await nursery.start(_sleep_forever_on_pool, pool)


@pytest.mark.trio
async def test_run_in_parallel(nursery):
    checkpoint = trio.lowlevel.checkpoint
    n_proc = 15
    n_workers = 2
    send_chan, recv_chan = trio.open_memory_channel(n_proc)

    async def return_arg(arg):
        await checkpoint()
        return arg

    async def run_and_send_result(pool, arg):
        result = await pool.run(return_arg, arg)
        await send_chan.send(result)

    with trio.fail_after(2):
        async with open_worker_pool(n_workers) as pool:
            for n in range(1, n_proc + 1):
                nursery.start_soon(run_and_send_result, pool, n)

            results = [await recv_chan.receive() for _ in range(n_proc)]
            assert sorted(results) == list(range(1, n_proc + 1))


@pytest.mark.trio
async def test_finished_pool_cannot_be_used():
    with trio.fail_after(2):
        async with open_worker_pool(1) as pool:
            await pool.run(trio.sleep, 0)

        with pytest.raises(WorkerPoolNotOpen):
            await pool.run(trio.sleep, 0)
