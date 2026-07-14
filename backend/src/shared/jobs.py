# src/shared/jobs.py
"""
Job name constants shared between the API (enqueues by name via
StreaqQueue.enqueue_unsafe) and the worker (registers a task under this
same name in worker.py). Keeping these in one place makes the dependency
between the two processes explicit -- if this string changes, both sides
break unless updated together.
"""

INGEST_EPISODE_JOB = "ingest_episode_job"