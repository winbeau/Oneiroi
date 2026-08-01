import hashlib

SERVICE_ASSERTION_HEADER = "X-Oneiroi-Service-Assertion"


def owner_id_for_access_subject(issuer: str, subject: str) -> str:
    normalized_issuer = issuer.strip().rstrip("/")
    normalized_subject = subject.strip()
    if not normalized_issuer or not normalized_subject:
        raise ValueError("issuer and subject are required")
    digest = hashlib.sha256(f"{normalized_issuer}\0{normalized_subject}".encode()).hexdigest()
    return f"access-{digest}"
