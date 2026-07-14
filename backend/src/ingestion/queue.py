# src/ingestion/queue.py
import asyncio
import functools
from contextlib import AsyncExitStack
from uuid import UUID, uuid4
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Callable, Awaitable, runtime_checkable

import coredis.exceptions
from streaq import Worker
from streaq.task import TaskStatus
from streaq.types import StreaqCancelled

from src.shared.jobs import INGEST_EPISODE_JOB


class JobStatus(Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class JobRecord:
    job_id: str
    episode_id: UUID
    status: JobStatus = JobStatus.QUEUED
    error: str | None = None


class JobNotFoundError(Exception):
    """No record of this job_id exists (never existed, or its result expired)."""
    pass


class DuplicateJobError(Exception):
    """Not currently raised -- dedup is Postgres's job (episode.pipeline_status
    checks in the ingest/reingest handlers), not the queue's. Kept for the
    public exception surface in case a future backend needs it."""
    pass


class QueueConnectionError(Exception):
    """Redis is unreachable. Distinct from job-level failures (JobNotFoundError,
    DuplicateJobError), which mean Redis answered but the job itself has a problem."""
    pass


def _wraps_redis_errors(method):
    @functools.wraps(method)
    async def wrapper(*args, **kwargs):
        try:
            return await method(*args, **kwargs)
        except coredis.exceptions.RedisError as e:
            raise QueueConnectionError(f"Redis error in {method.__name__}: {e}") from e
    return wrapper


@runtime_checkable
class IngestionQueue(Protocol):
    async def enqueue(self, episode_id: UUID, job_args: dict) -> str: ...
    async def get_status(self, job_id: str) -> JobStatus: ...
    async def cancel(self, job_id: str) -> bool: ...


class BackgroundTaskQueue:
    """In-process, single-machine ingestion queue -- the fallback path when
    REDIS_URL is unset."""

    def __init__(
        self,
        max_concurrent: int = 2,
        job_runner: Callable[[UUID, dict], Awaitable[None]] | None = None,
    ):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._jobs: dict[str, JobRecord] = {}
        self._job_runner = job_runner

    async def enqueue(self, episode_id: UUID, job_args: dict) -> str:
        job_id = str(uuid4())
        self._jobs[job_id] = JobRecord(job_id=job_id, episode_id=episode_id)
        asyncio.create_task(self._run(job_id, episode_id, job_args))
        return job_id

    async def _run(self, job_id: str, episode_id: UUID, job_args: dict):
        async with self._semaphore:
            if self._jobs[job_id].status == JobStatus.CANCELLED:
                return
            self._jobs[job_id].status = JobStatus.RUNNING
            try:
                if self._job_runner:
                    await self._job_runner(episode_id, job_args)
                self._jobs[job_id].status = JobStatus.DONE
            except Exception as e:
                self._jobs[job_id].status = JobStatus.FAILED
                self._jobs[job_id].error = str(e)
                raise

    async def get_status(self, job_id: str) -> JobStatus:
        record = self._jobs.get(job_id)
        if record is None:
            raise JobNotFoundError(f"No job found for job_id={job_id}")
        return record.status

    async def cancel(self, job_id: str) -> bool:
        record = self._jobs.get(job_id)
        if record and record.status == JobStatus.QUEUED:
            record.status = JobStatus.CANCELLED
            return True
        return False


class StreaqQueue:
    """Redis-backed ingestion queue via streaQ -- the default when REDIS_URL
    is set.

    Producer-only: enqueues jobs by function-name string (enqueue_unsafe) so
    the API process never imports pipeline code. The worker process
    (src/worker.py) is what actually registers and runs the job."""

    def __init__(self, redis_url: str, queue_name: str = "default"):
        self._worker = Worker(redis_url=redis_url, queue_name=queue_name)
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> "StreaqQueue":
        # streaQ requires its async context manager to be entered before any
        # Redis operation works, including enqueueing. We enter it once here
        # and hold it open for the app's lifetime, so callers never have to
        # think about it.
        await self._stack.enter_async_context(self._worker)
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._stack.aclose()

    @_wraps_redis_errors
    async def enqueue(self, episode_id: UUID, job_args: dict) -> str:
        task = self._worker.enqueue_unsafe(INGEST_EPISODE_JOB, episode_id, job_args)
        await task
        return task.id

    @_wraps_redis_errors
    async def get_status(self, job_id: str) -> JobStatus:
        status = await self._worker.status_by_id(job_id)
        if status == TaskStatus.NOT_FOUND:
            raise JobNotFoundError(f"No job found for job_id={job_id}")
        if status in (TaskStatus.QUEUED, TaskStatus.SCHEDULED):
            return JobStatus.QUEUED
        if status == TaskStatus.RUNNING:
            return JobStatus.RUNNING
        # DONE -- split by outcome. A small timeout (not 0) avoids a race where
        # the result isn't quite readable the instant status flips to DONE.
        result = await self._worker.result_by_id(job_id, timeout=2)
        if result.success:
            return JobStatus.DONE
        if isinstance(result.exception, StreaqCancelled):
            return JobStatus.CANCELLED
        return JobStatus.FAILED

    @_wraps_redis_errors
    async def cancel(self, job_id: str) -> bool:
        return await self._worker.abort_by_id(job_id)