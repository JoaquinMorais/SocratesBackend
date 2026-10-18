from sqlmodel import col, func, select

from models import ProjectStatus
from schemas.project_status import ProjectStatusPublic
from utils.statuses import to_public as status_public


def to_public(ps: ProjectStatus) -> ProjectStatusPublic:
    return ProjectStatusPublic(
        id_project_status=ps.id_project_status,
        id_project=ps.id_project,
        status_from=status_public(ps.status_from) if ps.status_from else None,
        status_to=status_public(ps.status_to),
        changed_at=ps.changed_at,
    )


async def record_status_change(
    db, id_project: int, id_status_from: int | None, id_status_to: int
) -> ProjectStatus:
    """Agrega un registro al historial de estados del proyecto (sin commit)."""
    ps = ProjectStatus(
        id_project=id_project,
        id_status_from=id_status_from,
        id_status_to=id_status_to,
    )
    db.add(ps)
    await db.flush()
    return ps


async def list_project_status_history(
    db, id_project: int, *, limit: int, offset: int
) -> tuple[list[ProjectStatus], int]:
    """Historial completo de un proyecto, en orden cronológico (más viejo primero)."""
    total = (
        await db.exec(
            select(func.count())
            .select_from(ProjectStatus)
            .where(ProjectStatus.id_project == id_project)
        )
    ).one()
    items = (
        await db.exec(
            select(ProjectStatus)
            .where(ProjectStatus.id_project == id_project)
            .order_by(col(ProjectStatus.id_project_status))
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(items), total
