import asyncio
import json
import time
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from oneiroi_common.runner_protocol import GPU_LEASE_KEY_PREFIX

LEASE_PREFIX = GPU_LEASE_KEY_PREFIX


@dataclass(frozen=True, slots=True)
class Lease:
    gpu_id: str
    session_id: str
    fencing_token: str
    expires_at_monotonic: float


class LeaseStore(Protocol):
    async def acquire(
        self,
        candidates: list[str],
        requested: int,
        session_id: str,
        *,
        ttl_seconds: float,
        allow_partial: bool,
    ) -> list[Lease]: ...

    async def renew_session(self, session_id: str, *, ttl_seconds: float) -> list[str]: ...

    async def release_gpu(self, gpu_id: str, session_id: str) -> bool: ...

    async def release_session(self, session_id: str) -> list[str]: ...

    async def active(self) -> dict[str, Lease]: ...


class InMemoryLeaseStore:
    def __init__(self) -> None:
        self._leases: dict[str, Lease] = {}
        self._lock = asyncio.Lock()

    async def acquire(
        self,
        candidates: list[str],
        requested: int,
        session_id: str,
        *,
        ttl_seconds: float,
        allow_partial: bool,
    ) -> list[Lease]:
        async with self._lock:
            self._remove_expired()
            selected = [gpu_id for gpu_id in candidates if gpu_id not in self._leases][:requested]
            if not allow_partial and len(selected) < requested:
                return []
            now = time.monotonic()
            leases = [
                Lease(
                    gpu_id=gpu_id,
                    session_id=session_id,
                    fencing_token=uuid4().hex,
                    expires_at_monotonic=now + ttl_seconds,
                )
                for gpu_id in selected
            ]
            self._leases.update({lease.gpu_id: lease for lease in leases})
            return leases

    async def renew_session(self, session_id: str, *, ttl_seconds: float) -> list[str]:
        async with self._lock:
            self._remove_expired()
            expires_at = time.monotonic() + ttl_seconds
            renewed: list[str] = []
            for gpu_id, lease in list(self._leases.items()):
                if lease.session_id != session_id:
                    continue
                self._leases[gpu_id] = Lease(
                    gpu_id=gpu_id,
                    session_id=session_id,
                    fencing_token=lease.fencing_token,
                    expires_at_monotonic=expires_at,
                )
                renewed.append(gpu_id)
            return renewed

    async def release_gpu(self, gpu_id: str, session_id: str) -> bool:
        async with self._lock:
            lease = self._leases.get(gpu_id)
            if lease is None or lease.session_id != session_id:
                return False
            del self._leases[gpu_id]
            return True

    async def release_session(self, session_id: str) -> list[str]:
        async with self._lock:
            released = [
                gpu_id for gpu_id, lease in self._leases.items() if lease.session_id == session_id
            ]
            for gpu_id in released:
                del self._leases[gpu_id]
            return released

    async def active(self) -> dict[str, Lease]:
        async with self._lock:
            self._remove_expired()
            return dict(self._leases)

    def _remove_expired(self) -> None:
        now = time.monotonic()
        expired = [
            gpu_id
            for gpu_id, lease in self._leases.items()
            if lease.expires_at_monotonic <= now
        ]
        for gpu_id in expired:
            del self._leases[gpu_id]


class RedisLeaseStore:
    _acquire_script = """
local requested = tonumber(ARGV[1])
local allow_partial = ARGV[2] == '1'
local session_id = ARGV[3]
local ttl_ms = tonumber(ARGV[4])
local selected = {}
for i, key in ipairs(KEYS) do
  if redis.call('EXISTS', key) == 0 and #selected < requested then
    table.insert(selected, key)
  end
end
if not allow_partial and #selected < requested then
  return {}
end
local result = {}
for _, key in ipairs(selected) do
  local token = redis.sha1hex(session_id .. key .. redis.call('TIME')[1] .. redis.call('TIME')[2])
  local payload = cjson.encode({sessionId=session_id, fencingToken=token})
  redis.call('SET', key, payload, 'PX', ttl_ms, 'NX')
  table.insert(result, key)
  table.insert(result, token)
end
return result
"""
    _renew_script = """
local session_id = ARGV[1]
local ttl_ms = tonumber(ARGV[2])
local renewed = {}
for _, key in ipairs(KEYS) do
  local payload = redis.call('GET', key)
  if payload then
    local value = cjson.decode(payload)
    if value.sessionId == session_id then
      redis.call('PEXPIRE', key, ttl_ms)
      table.insert(renewed, key)
    end
  end
end
return renewed
"""
    _release_script = """
local payload = redis.call('GET', KEYS[1])
if not payload then
  return 0
end
local value = cjson.decode(payload)
if value.sessionId ~= ARGV[1] then
  return 0
end
return redis.call('DEL', KEYS[1])
"""

    def __init__(self, redis_url: str) -> None:
        from redis.asyncio import Redis

        self.client = Redis.from_url(redis_url, decode_responses=True)

    async def acquire(
        self,
        candidates: list[str],
        requested: int,
        session_id: str,
        *,
        ttl_seconds: float,
        allow_partial: bool,
    ) -> list[Lease]:
        keys = [f"{LEASE_PREFIX}{gpu_id}" for gpu_id in candidates]
        if not keys:
            return []
        result = await self.client.eval(
            self._acquire_script,
            len(keys),
            *keys,
            requested,
            "1" if allow_partial else "0",
            session_id,
            int(ttl_seconds * 1000),
        )
        now = time.monotonic()
        leases = []
        for index in range(0, len(result), 2):
            key = result[index]
            leases.append(
                Lease(
                    gpu_id=key.removeprefix(LEASE_PREFIX),
                    session_id=session_id,
                    fencing_token=result[index + 1],
                    expires_at_monotonic=now + ttl_seconds,
                )
            )
        return leases

    async def renew_session(self, session_id: str, *, ttl_seconds: float) -> list[str]:
        keys = [key async for key in self.client.scan_iter(f"{LEASE_PREFIX}*")]
        if not keys:
            return []
        renewed = await self.client.eval(
            self._renew_script,
            len(keys),
            *keys,
            session_id,
            int(ttl_seconds * 1000),
        )
        return [key.removeprefix(LEASE_PREFIX) for key in renewed]

    async def release_gpu(self, gpu_id: str, session_id: str) -> bool:
        key = f"{LEASE_PREFIX}{gpu_id}"
        return bool(await self.client.eval(self._release_script, 1, key, session_id))

    async def release_session(self, session_id: str) -> list[str]:
        released: list[str] = []
        async for key in self.client.scan_iter(f"{LEASE_PREFIX}*"):
            if await self.client.eval(self._release_script, 1, key, session_id):
                released.append(key.removeprefix(LEASE_PREFIX))
        return released

    async def active(self) -> dict[str, Lease]:
        result: dict[str, Lease] = {}
        now = time.monotonic()
        async for key in self.client.scan_iter(f"{LEASE_PREFIX}*"):
            payload = await self.client.get(key)
            ttl_ms = await self.client.pttl(key)
            if payload and ttl_ms > 0:
                value = json.loads(payload)
                gpu_id = key.removeprefix(LEASE_PREFIX)
                result[gpu_id] = Lease(
                    gpu_id=gpu_id,
                    session_id=value["sessionId"],
                    fencing_token=value["fencingToken"],
                    expires_at_monotonic=now + ttl_ms / 1000,
                )
        return result

    async def close(self) -> None:
        await self.client.aclose()
