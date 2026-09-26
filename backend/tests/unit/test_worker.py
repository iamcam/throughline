# tests/unit/test_worker.py
from src import worker as worker_module
from src.ingestion.queue import INGEST_EPISODE_JOB


def _patch_settings(monkeypatch, **overrides):
    patched = worker_module.settings.model_copy(
        update={"redis_url": "redis://localhost:6379", **overrides}
    )
    monkeypatch.setattr(worker_module, "settings", patched)


def test_build_worker_holds_no_more_tasks_than_concurrency(monkeypatch):
    # Regression guard (Phase 20.2): streaQ's default prefetch buffer holds tasks
    # that are never liveness-renewed; behind long jobs they get reclaimed and run
    # twice. The worker must only ever hold tasks it is actively running.
    _patch_settings(monkeypatch, max_concurrent_ingestions=2)

    worker = worker_module.build_worker()

    assert worker.concurrency == 2
    assert worker.prefetch == worker.concurrency


def test_build_worker_applies_streaq_timeouts(monkeypatch):
    _patch_settings(monkeypatch, streaq_worker_idle_timeout=30, streaq_task_timeout=1234)

    worker = worker_module.build_worker()

    assert worker.idle_timeout == 30_000  # streaQ stores idle_timeout in ms
    assert worker.registry[INGEST_EPISODE_JOB].timeout == 1234