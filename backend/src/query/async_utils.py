#src/query/async_utils.py
import asyncio
from collections.abc import AsyncIterator
from typing import TypeVar

T = TypeVar("T")

async def with_heartbeat(source: AsyncIterator[T], interval: float) -> AsyncIterator[T | None]:
    """
    Passes through items from `source` as they arrive. If `interval` seconds
    pass with no item, yields None as a heartbeat tick and keeps waiting on
    the same pending item -- nothing from `source` is lost or skipped.
    """
    it = source.__aiter__()
    pending = asyncio.ensure_future(it.__anext__())
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if pending in done:
                try:
                    item = pending.result()
                except StopAsyncIteration:
                    return
                yield item
                pending = asyncio.ensure_future(it.__anext__())
            else:
                yield None
    finally:
        if not pending.done():
            pending.cancel()