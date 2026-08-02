import os
import stat
import time
import uuid
from pathlib import Path

import jwt


class ServiceAuthenticationError(Exception):
    pass


class ServiceAuthConfigurationError(Exception):
    pass


class ServiceAssertionSigner:
    def __init__(
        self,
        private_key_file: Path | None,
        *,
        issuer: str,
        audience: str,
        key_id: str,
        lifetime_seconds: int = 60,
    ) -> None:
        self.private_key_file = private_key_file
        self.issuer = issuer.strip()
        self.audience = audience.strip()
        self.key_id = key_id.strip()
        self.lifetime_seconds = lifetime_seconds
        self._private_key: bytes | None = None

    def issue(self, owner_id: str) -> str:
        if self.private_key_file is None or not self.issuer or not self.audience:
            raise ServiceAuthConfigurationError("service assertion signing is not configured")
        now = int(time.time())
        headers = {"kid": self.key_id} if self.key_id else None
        return jwt.encode(
            {
                "iss": self.issuer,
                "sub": owner_id,
                "aud": self.audience,
                "iat": now,
                "exp": now + self.lifetime_seconds,
                "jti": uuid.uuid4().hex,
            },
            self._load_private_key(),
            algorithm="RS256",
            headers=headers,
        )

    def _load_private_key(self) -> bytes:
        if self._private_key is not None:
            return self._private_key
        assert self.private_key_file is not None
        descriptor: int | None = None
        try:
            path_metadata = os.lstat(self.private_key_file)
            if stat.S_ISLNK(path_metadata.st_mode):
                raise ServiceAuthConfigurationError("service private key must not be a symlink")
            flags = (
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOINHERIT", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            descriptor = os.open(self.private_key_file, flags)
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or (path_metadata.st_dev, path_metadata.st_ino)
                != (metadata.st_dev, metadata.st_ino)
            ):
                raise ServiceAuthConfigurationError("service private key is not a regular file")
            if os.name != "nt" and stat.S_IMODE(metadata.st_mode) & 0o077:
                raise ServiceAuthConfigurationError(
                    "service private key must not be group/world accessible"
                )
            with os.fdopen(descriptor, "rb") as source:
                descriptor = None
                key = source.read()
        except OSError as exc:
            raise ServiceAuthConfigurationError("service private key is unavailable") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if not key:
            raise ServiceAuthConfigurationError("service private key is empty")
        self._private_key = key
        return key


class ServiceAssertionValidator:
    def __init__(
        self,
        public_key_file: Path | None,
        *,
        issuer: str,
        audience: str,
        clock_skew_seconds: float = 10,
    ) -> None:
        self.public_key_file = public_key_file
        self.issuer = issuer.strip()
        self.audience = audience.strip()
        self.clock_skew_seconds = clock_skew_seconds
        self._public_key: bytes | None = None

    def validate(self, assertion: str) -> str:
        if self.public_key_file is None or not self.issuer or not self.audience:
            raise ServiceAuthConfigurationError("service assertion validation is not configured")
        try:
            claims = jwt.decode(
                assertion.strip(),
                key=self._load_public_key(),
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.clock_skew_seconds,
                options={"require": ["iss", "sub", "aud", "iat", "exp", "jti"]},
            )
        except (jwt.InvalidTokenError, TypeError, ValueError) as exc:
            raise ServiceAuthenticationError("service assertion is invalid") from exc
        owner_id = claims.get("sub")
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise ServiceAuthenticationError("service assertion subject is invalid")
        return owner_id.strip()

    def _load_public_key(self) -> bytes:
        if self._public_key is not None:
            return self._public_key
        assert self.public_key_file is not None
        try:
            key = self.public_key_file.read_bytes()
        except OSError as exc:
            raise ServiceAuthConfigurationError("service public key is unavailable") from exc
        if not key:
            raise ServiceAuthConfigurationError("service public key is empty")
        self._public_key = key
        return key
