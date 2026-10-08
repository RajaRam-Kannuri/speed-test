from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import AuditLog

log = logging.getLogger("lorvenlax.audit")


def record(
    db: Session,
    action: str,
    *,
    organization_id: Optional[uuid.UUID] = None,
    project_id: Optional[uuid.UUID] = None,
    user_id: Optional[uuid.UUID] = None,
    resource_type: Optional[str] = None,
    resource_id: Any = None,
    details: Optional[dict[str, Any]] = None,
    ip_address: Optional[str] = None,
) -> None:
    """Add an audit entry to the current transaction. Never put secret values in details."""
    db.add(
        AuditLog(
            organization_id=organization_id,
            project_id=project_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            details=details or {},
            ip_address=ip_address,
        )
    )
    log.info("audit action=%s resource=%s:%s user=%s", action, resource_type, resource_id, user_id)
