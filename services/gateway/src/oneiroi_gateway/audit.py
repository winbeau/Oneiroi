import hashlib
import logging

logger = logging.getLogger("oneiroi.audit")


def audit_event(
    action: str,
    owner_id: str,
    *,
    resource_id: str | None = None,
    outcome: str,
    reason: str | None = None,
) -> None:
    owner_hash = hashlib.sha256(owner_id.encode()).hexdigest()[:12]
    logger.info(
        "audit action=%s owner=%s resource=%s outcome=%s reason=%s",
        action,
        owner_hash,
        resource_id or "-",
        outcome,
        reason or "-",
    )
