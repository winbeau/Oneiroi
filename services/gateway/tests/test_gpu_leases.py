import asyncio

import pytest

from oneiroi_gateway.redis.leases import InMemoryLeaseStore


@pytest.mark.asyncio
async def test_concurrent_allocations_never_double_lease() -> None:
    store = InMemoryLeaseStore()

    first, second = await asyncio.gather(
        store.acquire(["GPU-a"], 1, "session-a", ttl_seconds=60, allow_partial=True),
        store.acquire(["GPU-a"], 1, "session-b", ttl_seconds=60, allow_partial=True),
    )

    assert sorted([len(first), len(second)]) == [0, 1]
    active = await store.active()
    assert list(active) == ["GPU-a"]


@pytest.mark.asyncio
async def test_release_clears_only_session_leases() -> None:
    store = InMemoryLeaseStore()
    await store.acquire(["GPU-a"], 1, "session-a", ttl_seconds=60, allow_partial=True)
    await store.acquire(["GPU-b"], 1, "session-b", ttl_seconds=60, allow_partial=True)

    assert await store.release_session("session-a") == ["GPU-a"]
    assert list(await store.active()) == ["GPU-b"]
