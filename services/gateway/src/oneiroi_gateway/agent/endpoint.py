import hashlib
from urllib.parse import urlsplit, urlunsplit


def provider_endpoint_hash(base_url: str) -> str:
    parsed = urlsplit(base_url)
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    if port is not None and not (
        (parsed.scheme.lower() == "https" and port == 443)
        or (parsed.scheme.lower() == "http" and port == 80)
    ):
        hostname = f"{hostname}:{port}"
    normalized = urlunsplit(
        (
            parsed.scheme.lower(),
            hostname,
            parsed.path.rstrip("/") or "/",
            "",
            "",
        )
    )
    return hashlib.sha256(normalized.encode()).hexdigest()
