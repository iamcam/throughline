# backend/src/worker_cli.py
"""
streaQ CLI entry point (`streaq run src.worker_cli:worker`).

Kept separate from src/worker.py so importing build_worker() elsewhere
(app.py) never also triggers this eager construction as an import
side effect.
"""
from src.worker import build_worker

worker = build_worker()