# tests/unit/test_background_queue.py
import pytest
import asyncio
from uuid import uuid4

from src.ingestion.queue import BackgroundTaskQueue, IngestionQueue, JobStatus, JobNotFoundError


async def test_enqueue_returns_job_id():
    async def worker(episode_id, job_args):
        pass

    queue = BackgroundTaskQueue(max_concurrent=2, job_runner=worker)
    job_id = await queue.enqueue(uuid4(), {})
    assert isinstance(job_id, str)


async def test_get_status_transitions_to_done():
    async def worker(episode_id, job_args):
        await asyncio.sleep(0.05)

    queue = BackgroundTaskQueue(max_concurrent=1, job_runner=worker)
    job_id = await queue.enqueue(uuid4(), {})

    assert await queue.get_status(job_id) in (JobStatus.QUEUED, JobStatus.RUNNING)

    await asyncio.sleep(0.1)
    assert await queue.get_status(job_id) == JobStatus.DONE


async def test_get_status_reports_failed():
    async def worker(episode_id, job_args):
        raise RuntimeError("intentional test failure")

    queue = BackgroundTaskQueue(max_concurrent=1, job_runner=worker)
    job_id = await queue.enqueue(uuid4(), {})

    await asyncio.sleep(0.1)
    assert await queue.get_status(job_id) == JobStatus.FAILED


async def test_get_status_unknown_job_raises():
    queue = BackgroundTaskQueue(max_concurrent=2, job_runner=None)
    with pytest.raises(JobNotFoundError):
        await queue.get_status(str(uuid4()))


async def test_cancel_queued_job_succeeds():
    async def worker(episode_id, job_args):
        await asyncio.sleep(0.05)

    # max_concurrent=1 with two jobs enqueued back-to-back: the first
    # claims the semaphore immediately, the second stays QUEUED long
    # enough to cancel before it ever starts running.
    queue = BackgroundTaskQueue(max_concurrent=1, job_runner=worker)
    await queue.enqueue(uuid4(), {})
    second_job_id = await queue.enqueue(uuid4(), {})

    cancelled = await queue.cancel(second_job_id)
    assert cancelled is True
    assert await queue.get_status(second_job_id) == JobStatus.CANCELLED


async def test_cancel_running_job_fails():
    async def worker(episode_id, job_args):
        await asyncio.sleep(0.1)

    queue = BackgroundTaskQueue(max_concurrent=1, job_runner=worker)
    job_id = await queue.enqueue(uuid4(), {})
    await asyncio.sleep(0.02)  # let it actually start running

    cancelled = await queue.cancel(job_id)
    assert cancelled is False  # BackgroundTaskQueue only cancels QUEUED jobs


async def test_semaphore_limits_concurrency():
    running = []
    max_seen = 0

    async def tracking_worker(episode_id, job_args):
        running.append(1)
        nonlocal max_seen
        max_seen = max(max_seen, len(running))
        await asyncio.sleep(0.05)
        running.pop()

    queue = BackgroundTaskQueue(max_concurrent=2, job_runner=tracking_worker)
    job_ids = [await queue.enqueue(uuid4(), {}) for _ in range(4)]
    await asyncio.sleep(0.3)

    assert max_seen <= 2


def test_satisfies_protocol():
    queue = BackgroundTaskQueue(max_concurrent=2, job_runner=None)
    assert isinstance(queue, IngestionQueue)