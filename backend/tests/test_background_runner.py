import asyncio
import unittest

from app.services.background_runner import BackgroundTaskRunner


class BackgroundTaskRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_key_runs_in_submission_order(self):
        runner = BackgroundTaskRunner("test", max_concurrency=4)
        order = []
        release_first = asyncio.Event()

        async def first():
            order.append("first:start")
            await release_first.wait()
            order.append("first:end")

        async def second():
            order.append("second")

        runner.submit("conversation-1", first)
        runner.submit("conversation-1", second)
        await asyncio.sleep(0.01)
        self.assertEqual(order, ["first:start"])
        release_first.set()
        await runner.drain(timeout=1)
        self.assertEqual(order, ["first:start", "first:end", "second"])
        self.assertEqual(runner._keys, {})

    async def test_concurrency_is_bounded_across_keys(self):
        runner = BackgroundTaskRunner("test", max_concurrency=2)
        running = 0
        peak = 0
        release = asyncio.Event()

        async def work():
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await release.wait()
            running -= 1

        for key in range(5):
            runner.submit(key, work)
        await asyncio.sleep(0.01)
        self.assertEqual(peak, 2)
        release.set()
        await runner.drain(timeout=1)
        self.assertEqual(runner.pending_count, 0)

    async def test_failures_are_contained_and_drain_cancels_stragglers(self):
        runner = BackgroundTaskRunner("test", max_concurrency=2)

        async def broken():
            raise RuntimeError("provider unavailable")

        async def endless():
            await asyncio.Event().wait()

        failed = runner.submit("a", broken)
        stuck = runner.submit("b", endless)
        await asyncio.sleep(0.01)
        self.assertTrue(failed.done())
        self.assertIsNone(failed.exception())

        await runner.drain(timeout=0.05)
        self.assertTrue(stuck.cancelled())
        self.assertEqual(runner.pending_count, 0)


if __name__ == "__main__":
    unittest.main()
