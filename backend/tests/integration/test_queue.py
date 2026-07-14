# tests/integration/test_queue.py
"""
Contract tests for IngestionQueue implementations. Both BackgroundTaskQueue
and StreaqQueue must satisfy the same behavior from a caller's perspective --
every test here runs against both, via the parametrized `queue_cm` fixture.

Requires a running Postgres and Redis (see backend/README.md).

Note: queue_cm is a *sync* fixture returning an unentered async context
manager, not the more typical async-generator-with-yield fixture. StreaqQueue's
__aenter__/__aexit__ must run within a single continuous coroutine for anyio's
CancelScope bookkeeping to work correctly -- spanning them across a pytest
fixture's yield boundary causes a spurious "different task" RuntimeError.
Each test does `async with queue_cm as queue:` itself instead.

Scope note: only covers Protocol conformance and basic enqueue/get_status
behavior. Full lifecycle tests (RUNNING/DONE/FAILED/CANCELLED transitions)
are tracked as a follow-up -- see Future Scope 2.1e.
"""
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from src.config import get_settings
from src.ingestion.queue import (
    BackgroundTaskQueue,
    StreaqQueue,
    IngestionQueue,
    JobNotFoundError,
)

TEST_QUEUE_NAME_PREFIX = "test"


async def _noop_job_runner(episode_id, job_args) -> None:
    pass


@asynccontextmanager
async def _background_queue_cm():
    yield BackgroundTaskQueue(max_concurrent=5, job_runner=_noop_job_runner)


@pytest.fixture(params=["background", "streaq"])
def queue_cm(request):
    if request.param == "background":
        return _background_queue_cm()
    redis_url = get_settings().redis_url
    queue_name = f"{TEST_QUEUE_NAME_PREFIX}-{uuid4().hex[:8]}"
    return StreaqQueue(redis_url=redis_url, queue_name=queue_name)


async def test_satisfies_protocol(queue_cm):
    async with queue_cm as queue:
        assert isinstance(queue, IngestionQueue)


async def test_enqueue_returns_job_id(queue_cm):
    async with queue_cm as queue:
        job_id = await queue.enqueue(uuid4(), {})
        assert isinstance(job_id, str)


async def test_get_status_unknown_job_raises(queue_cm):
    async with queue_cm as queue:
        with pytest.raises(JobNotFoundError):
            await queue.get_status(str(uuid4()))