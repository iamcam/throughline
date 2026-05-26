import pytest
import asyncio
from src.ingestion.queue import BackgroundTaskQueue, IngestionQueue
from uuid import uuid4

async def test_engqueue_returns_job_id():
    queue = BackgroundTaskQueue(max_concurrent=2)
    job_id = await queue.enqueue(uuid4(), {}, worker=None)
    assert isinstance(job_id, str)

async def test_queue_position_reported():
    ran = []

    async def slow_worker(episode_id, job_args):
        await  asyncio.sleep(0.05)
        ran.append(episode_id)

    queue = BackgroundTaskQueue(max_concurrent=1)
    await queue.enqueue(uuid4(), {}, worker = slow_worker)
    job_id = await queue.enqueue(uuid4(), {}, worker=slow_worker)

    position = await queue.get_position(job_id)
    assert position > 0

async def test_semaphore_limits_concurrency():
    running = []
    max_seen = 0

    async def tracking_worker(episode_id, job_args):
        running.append(1)
        nonlocal max_seen
        max_seen = max(max_seen, len(running))
        await asyncio.sleep(0.05)
        running.pop()

    queue = BackgroundTaskQueue(max_concurrent=2)
    tasks = [queue.enqueue(uuid4(), {}, worker=tracking_worker) for _ in range(4)]
    await asyncio.gather(*tasks)
    await asyncio.sleep(0.3)

    assert max_seen <= 2

def test_queue_statistics_protocol():
    queue = BackgroundTaskQueue(max_concurrent=2)
    assert isinstance(queue, IngestionQueue)