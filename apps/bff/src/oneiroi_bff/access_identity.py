import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

from oneiroi_common.identity import owner_id_for_access_subject


class AccessAuthenticationError(Exception):
    pass


class AccessConfigurationError(Exception):
    pass


class AccessVerificationUnavailableError(Exception):
    pass


@dataclass(frozen=True)
class AccessIdentity:
    issuer: str
    subject: str
    owner_id: str


class CloudflareAccessJwtValidator:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str,
        cache_seconds: float = 300,
        clock_skew_seconds: float = 30,
    ) -> None:
        self.issuer = issuer.strip().rstrip("/")
        self.audience = audience.strip()
        self.jwks_url = jwks_url.strip()
        self.cache_seconds = cache_seconds
        self.clock_skew_seconds = clock_skew_seconds
        self._keys: dict[str, Any] = {}
        self._cache_expires_at = 0.0
        self._lock = asyncio.Lock()

    async def validate(self, assertion: str) -> AccessIdentity:
        if not self.issuer or not self.audience or not self.jwks_url:
            raise AccessConfigurationError("Cloudflare Access JWT validation is not configured")
        token = assertion.strip()
        if not token:
            raise AccessAuthenticationError("Cloudflare Access assertion is missing")
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if header.get("alg") != "RS256" or not isinstance(kid, str) or not kid:
                raise AccessAuthenticationError("Cloudflare Access assertion header is invalid")
            key = await self._key_for(kid)
            claims = jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.clock_skew_seconds,
                options={"require": ["iss", "sub", "aud", "exp"]},
            )
        except AccessAuthenticationError:
            raise
        except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as exc:
            raise AccessAuthenticationError("Cloudflare Access assertion is invalid") from exc

        subject = claims.get("sub")
        issuer = claims.get("iss")
        if not isinstance(subject, str) or not subject.strip() or issuer != self.issuer:
            raise AccessAuthenticationError("Cloudflare Access identity claims are invalid")
        return AccessIdentity(
            issuer=self.issuer,
            subject=subject.strip(),
            owner_id=owner_id_for_access_subject(self.issuer, subject),
        )

    async def _key_for(self, kid: str) -> Any:
        now = time.monotonic()
        if now < self._cache_expires_at and kid in self._keys:
            return self._keys[kid]
        async with self._lock:
            now = time.monotonic()
            if now >= self._cache_expires_at or kid not in self._keys:
                jwks = await self._fetch_jwks()
                keys = self._parse_keys(jwks)
                self._keys = keys
                self._cache_expires_at = now + self.cache_seconds
            try:
                return self._keys[kid]
            except KeyError as exc:
                raise AccessAuthenticationError("Cloudflare Access signing key is unknown") from exc

    async def _fetch_jwks(self) -> Mapping[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=5,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.get(self.jwks_url, headers={"Accept": "application/json"})
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AccessVerificationUnavailableError(
                "Cloudflare Access signing keys are unavailable"
            ) from exc
        if not isinstance(payload, Mapping):
            raise AccessVerificationUnavailableError(
                "Cloudflare Access signing keys are invalid"
            )
        return payload

    @staticmethod
    def _parse_keys(jwks: Mapping[str, Any]) -> dict[str, Any]:
        raw_keys = jwks.get("keys")
        if not isinstance(raw_keys, list):
            raise AccessVerificationUnavailableError(
                "Cloudflare Access signing keys are invalid"
            )
        parsed: dict[str, Any] = {}
        for raw_key in raw_keys:
            if not isinstance(raw_key, dict):
                continue
            kid = raw_key.get("kid")
            if not isinstance(kid, str) or not kid:
                continue
            try:
                key = jwt.PyJWK.from_dict(raw_key, algorithm="RS256").key
            except (jwt.PyJWKError, TypeError, ValueError):
                continue
            parsed[kid] = key
        if not parsed:
            raise AccessVerificationUnavailableError(
                "Cloudflare Access signing keys are empty"
            )
        return parsed
