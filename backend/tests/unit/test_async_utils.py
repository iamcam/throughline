# tests/unit/test_async_utils.py
import asyncio
import pytest

from src.query.async_utils import with_heartbeat


async def _slow_source(delays_and_items):
    for delay, item in delays_and_items:
        await asyncio.sleep(delay)
        yield item


@pytest.mark.asyncio
async def test_fast_source_passes_through_without_heartbeats():
    source = _slow_source([(0, "a"), (0, "b"), (0, "c")])
    items = [item async for item in with_heartbeat(source, interval=1.0)]
    assert items == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_slow_item_triggers_heartbeats_then_arrives():
    source = _slow_source([(0.12, "late")])
    items = [item async for item in with_heartbeat(source, interval=0.05)]

    assert items[-1] == "late"
    assert items[:-1] == [None] * (len(items) - 1)
    assert len(items) >= 2  # at least one heartbeat fired before the item showed up


@pytest.mark.asyncio
async def test_heartbeats_only_appear_before_slow_items():
    source = _slow_source([(0, "fast"), (0.12, "slow"), (0, "fast2")])
    items = [item async for item in with_heartbeat(source, interval=0.05)]

    assert items[0] == "fast"
    assert items[-2] == "slow"
    assert items[-1] == "fast2"
    heartbeats = items[1:-2]
    assert heartbeats and all(x is None for x in heartbeats)


@pytest.mark.asyncio
async def test_empty_source_yields_nothing():
    async def _empty():
        return
        yield  # unreachable, but makes this an async generator function

    items = [item async for item in with_heartbeat(_empty(), interval=1.0)]
    assert items == []


@pytest.mark.asyncio
async def test_source_exception_propagates():
    async def _boom():
        yield "ok"
        raise ValueError("source broke")

    items = []
    with pytest.raises(ValueError):
        async for item in with_heartbeat(_boom(), interval=1.0):
            items.append(item)
    assert items == ["ok"]


@pytest.mark.asyncio
async def test_aclose_cancels_pending_task():
    cancelled = False

    async def _hangs():
        nonlocal cancelled
        try:
            await asyncio.sleep(10)
            yield "should not reach"
        except asyncio.CancelledError:
            cancelled = True
            raise

    gen = with_heartbeat(_hangs(), interval=0.05)
    first = await gen.__anext__()
    assert first is None  # heartbeat, since the source is still asleep

    await gen.aclose()
    await asyncio.sleep(0.01)  # let the cancellation actually propagate into _hangs()
    assert cancelled