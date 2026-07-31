import os
from uuid import uuid4

import pytest

from oneiroi_gateway.redis.leases import RedisLeaseStore

pytestmark = pytest.mark.skipif(
    os.getenv("ONEIROI_TEST_REDIS") != "1",
    reason="set ONEIROI_TEST_REDIS=1 for the loopback Redis integration test",
)


@pytest.mark.asyncio
async def test_redis_lease_acquisition_is_atomic() -> None:
    store = RedisLeaseStore(os.getenv("ONEIROI_GATEWAY_REDIS_URL", "redis://127.0.0.1:6379/0"))
    suffix = uuid4().hex
    gpus = [f"GPU-integration-a-{suffix}", f"GPU-integration-b-{suffix}"]
    session = f"session-{suffix}"
    try:
        leases = await store.acquire(
            gpus,
            2,
            session,
            ttl_seconds=30,
            allow_partial=False,
        )
        competing = await store.acquire(
            gpus,
            1,
            f"competing-{suffix}",
            ttl_seconds=30,
            allow_partial=True,
        )

        assert {lease.gpu_id for lease in leases} == set(gpus)
        assert competing == []
        active = await store.active()
        assert all(active[gpu_id].session_id == session for gpu_id in gpus)
        assert set(await store.release_session(session)) == set(gpus)
    finally:
        await store.release_session(session)
        await store.release_session(f"competing-{suffix}")
        await store.close()
