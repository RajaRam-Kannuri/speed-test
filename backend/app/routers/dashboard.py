from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents.reporting import project_dashboard
from ..db import get_db
from ..deps import Principal, get_principal, load_project, require_org_role
from ..models import Project

router = APIRouter(tags=["dashboard & reports"])


@router.get("/organizations/{org_id}/dashboard")
def org_dashboard(org_id: uuid.UUID, project_id: Optional[uuid.UUID] = None, days: int = 14,
                  principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    require_org_role(db, principal, org_id, "viewer")
    if project_id:
        project = load_project(db, principal, project_id, "viewer")
        ids = [project.id] if project.organization_id == org_id else []
    else:
        ids = list(db.scalars(select(Project.id).where(Project.organization_id == org_id)))
    return project_dashboard(db, ids, days=max(1, min(days, 90)))
