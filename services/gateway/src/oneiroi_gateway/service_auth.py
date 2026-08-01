from pathlib import Path

import jwt


class ServiceAuthenticationError(Exception):
    pass


class ServiceAuthConfigurationError(Exception):
    pass


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
