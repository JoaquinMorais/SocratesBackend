from datetime import datetime

from sqlmodel import SQLModel

from schemas.status import StatusPublic


class ProjectStatusPublic(SQLModel):
    id_project_status: int
    id_project: int
    status_from: StatusPublic | None = None
    status_to: StatusPublic
    changed_at: datetime


class ProjectStatusList(SQLModel):
    items: list[ProjectStatusPublic]
    total: int
    limit: int
    offset: int
