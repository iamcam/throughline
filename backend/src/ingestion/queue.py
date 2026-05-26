import asyncio
from uuid import UUID, uuid4
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, Callable, Awaitable, runtime_checkable


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

@runtime_checkable
class IngestionQueue(Protocol):
    async def enqueue(self, episode_id: UUID, job_args: dict) -> str: ...
    async def get_status(self, job_id: str) -> JobStatus: ...
    async def get_position(self, job_id: str) -> int: ...
    async def cancel(self, job_id: str) -> bool: ...


class BackgroundTaskQueue:
    def __init__(self, max_concurrent: int = 2):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._jobs: dict[str, JobRecord] = {}
        self._queue: list[str] = []  # job_ids waiting for semaphore

    async def enqueue(
        self,
        episode_id: UUID,
        job_args: dict,
        worker: Callable[[UUID, dict], Awaitable[None]] | None = None,
    ) -> str:
        job_id = str(uuid4())
        self._jobs[job_id] = JobRecord(job_id=job_id, episode_id=episode_id)
        self._queue.append(job_id)
        asyncio.create_task(self._run(job_id, episode_id, job_args, worker))
        return job_id

    async def _run(
        self,
        job_id: str,
        episode_id: UUID,
        job_args: dict,
        worker: Callable | None,
    ):
        async with self._semaphore:
            if job_id in self._queue:
                self._queue.remove(job_id)
            self._jobs[job_id].status = JobStatus.RUNNING
            try:
                if worker:
                    await worker(episode_id, job_args)
                self._jobs[job_id].status = JobStatus.DONE
            except Exception as e:
                self._jobs[job_id].status = JobStatus.FAILED
                self._jobs[job_id].error = str(e)
                raise

    async def get_status(self, job_id: str) -> JobStatus:
        record = self._jobs.get(job_id)
        return record.status if record else JobStatus.FAILED

    async def get_position(self, job_id: str) -> int:
        try:
            return self._queue.index(job_id) + 1
        except ValueError:
            return 0

    async def cancel(self, job_id: str) -> bool:
        if job_id in self._queue:
            self._queue.remove(job_id)
            self._jobs[job_id].status = JobStatus.CANCELLED
            return True
        return False