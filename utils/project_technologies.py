from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from models import ProjectTechnology, Technology
from utils.projects import Access, get_project
from utils.technologies import get_technology


def _manage_forbidden() -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Only a professor of this section year, a super admin or a group member "
        "can manage this project's technologies",
    )


def _final_conflict() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        "A project in a final state cannot modify its technologies",
    )


def _already_linked() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT, "Technology is already linked to this project"
    )


def _link_not_found() -> HTTPException:
    return HTTPException(
        status.HTTP_404_NOT_FOUND, "Technology is not linked to this project"
    )


async def _project_to_manage(db, access: Access, id_project: int):
    """Checks de modificación: 404 si el proyecto no existe, 403 si no es
    privilegiado y 409 si el proyecto está en un estado final."""
    project = await get_project(db, id_project)
    if not access.is_privileged(project):
        raise _manage_forbidden()
    if project.status.is_final:
        raise _final_conflict()
    return project


async def add_technology(
    db, access: Access, id_project: int, id_technology: int
) -> Technology:
    await _project_to_manage(db, access, id_project)
    technology = await get_technology(db, id_technology)
    link = await db.get(ProjectTechnology, (id_project, id_technology))
    if link:
        raise _already_linked()
    db.add(ProjectTechnology(id_project=id_project, id_technology=id_technology))
    try:
        await db.commit()
    except IntegrityError:  # dos altas simultáneas con el mismo par
        await db.rollback()
        raise _already_linked()
    return technology


async def add_technologies_bulk(
    db, access: Access, id_project: int, id_technologies: list[int]
) -> list[Technology]:
    """Todo o nada: si alguna fila falla, no se vincula ninguna."""
    await _project_to_manage(db, access, id_project)

    errors: list[dict] = []
    first_row: dict[int, int] = {}  # id_technology -> primera fila donde aparece
    for row, id_technology in enumerate(id_technologies, start=1):
        if id_technology in first_row:
            errors.append(
                {
                    "row": row,
                    "id_technology": id_technology,
                    "detail": f"Duplicated in the request (first seen in row {first_row[id_technology]})",
                }
            )
        else:
            first_row[id_technology] = row

    ids = list(first_row)
    existing_ids = set(
        (
            await db.exec(
                select(Technology.id_technology).where(
                    col(Technology.id_technology).in_(ids)
                )
            )
        ).all()
    )
    for id_technology, row in first_row.items():
        if id_technology not in existing_ids:
            errors.append(
                {
                    "row": row,
                    "id_technology": id_technology,
                    "detail": "Technology not found",
                }
            )
    linked_ids = set(
        (
            await db.exec(
                select(ProjectTechnology.id_technology).where(
                    ProjectTechnology.id_project == id_project,
                    ProjectTechnology.id_technology.in_(ids),
                )
            )
        ).all()
    )
    for id_technology, row in first_row.items():
        if id_technology in linked_ids:
            errors.append(
                {
                    "row": row,
                    "id_technology": id_technology,
                    "detail": "Technology is already linked to this project",
                }
            )

    if errors:
        errors.sort(key=lambda e: e["row"])
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=errors)

    for id_technology in ids:
        db.add(ProjectTechnology(id_project=id_project, id_technology=id_technology))
    try:
        await db.commit()
    except IntegrityError:  # dos lotes simultáneos con la misma tecnología
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Technologies changed while adding, try again"
        )

    items = (
        await db.exec(
            select(Technology)
            .where(col(Technology.id_technology).in_(ids))
            .order_by(col(Technology.name), col(Technology.id_technology))
        )
    ).all()
    return list(items)


async def remove_technology(
    db, access: Access, id_project: int, id_technology: int
) -> None:
    await _project_to_manage(db, access, id_project)
    link = await db.get(ProjectTechnology, (id_project, id_technology))
    if not link:
        raise _link_not_found()
    await db.delete(link)
    await db.commit()


async def list_project_technologies(
    db, access: Access, id_project: int, *, q: str | None, limit: int, offset: int
) -> tuple[list[Technology], int]:
    project = await get_project(db, id_project)
    if not access.can_see_project(project):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This project is private")

    conditions = [ProjectTechnology.id_project == id_project]
    if q:
        conditions.append(col(Technology.name).ilike(f"%{q.strip()}%"))
    total = (
        await db.exec(
            select(func.count())
            .select_from(ProjectTechnology)
            .join(Technology, ProjectTechnology.id_technology == Technology.id_technology)
            .where(*conditions)
        )
    ).one()
    items = (
        await db.exec(
            select(Technology)
            .join(
                ProjectTechnology,
                ProjectTechnology.id_technology == Technology.id_technology,
            )
            .where(*conditions)
            .order_by(col(Technology.name), col(Technology.id_technology))
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(items), total
