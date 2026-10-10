# tests/integration/test_queue.py
"""
Contract tests for IngestionQueue implementations. Both BackgroundTaskQueue
and StreaqQueue must satisfy the same behavior from a caller's perspective --
every test here runs against both, via the parametrized `queue_cm` fixture.

Requires a running Postgres and Redis (see docs/README-backend.md).

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

from tests.conftest import noop_before_submit
from src.config import get_settings
from src.ingestion.queue import (
    BackgroundTaskQueue,
    StreaqQueue,
    IngestionQueue,
    JobNotFoundError,
)

TEST_QUEUE_NAME_PREFIX = "test"

class _CallbackFailed(Exception):
    pass

async def _noop_job_runner(episode_id, job_args, job_id) -> None:
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
        job_id = await queue.enqueue(uuid4(), {}, before_submit=noop_before_submit)
        assert isinstance(job_id, str)


async def test_get_status_unknown_job_raises(queue_cm):
    async with queue_cm as queue:
        with pytest.raises(JobNotFoundError):
            await queue.get_status(str(uuid4()))



async def test_before_submit_runs_before_job_is_visible(queue_cm):
    seen = {}
    async with queue_cm as queue:
        async def before_submit(job_id: str) -> None:
            seen["job_id"] = job_id
            with pytest.raises(JobNotFoundError):
                await queue.get_status(job_id)

        returned_id = await queue.enqueue(uuid4(), {}, before_submit=before_submit)

        assert returned_id == seen["job_id"]
        await queue.get_status(returned_id)  # visible now -- must not raise


async def test_failing_before_submit_prevents_submission(queue_cm):
    seen = {}
    async with queue_cm as queue:
        async def before_submit(job_id: str) -> None:
            seen["job_id"] = job_id
            raise _CallbackFailed()

        with pytest.raises(_CallbackFailed):
            await queue.enqueue(uuid4(), {}, before_submit=before_submit)

        with pytest.raises(JobNotFoundError):
            await queue.get_status(seen["job_id"])