from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from models import Technology
from schemas.technology import (
    TechnologyCreate,
    TechnologyPublic,
    TechnologyUpdate,
)


def to_public(technology: Technology) -> TechnologyPublic:
    return TechnologyPublic(
        id_technology=technology.id_technology,
        name=technology.name,
        description=technology.description,
    )


def _duplicate() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT, "A technology with this name already exists"
    )


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Technology not found")


async def get_technology(db, id_technology: int) -> Technology:
    technology = await db.get(Technology, id_technology)
    if not technology:
        raise _not_found()
    return technology


async def _name_taken(db, name: str, exclude_id: int | None = None) -> bool:
    stmt = select(Technology.id_technology).where(
        func.lower(col(Technology.name)) == name.lower()
    )
    if exclude_id is not None:
        stmt = stmt.where(Technology.id_technology != exclude_id)
    return (await db.exec(stmt)).first() is not None


async def create_technology(db, data: TechnologyCreate) -> Technology:
    if await _name_taken(db, data.name):
        raise _duplicate()
    technology = Technology(name=data.name, description=data.description)
    db.add(technology)
    try:
        await db.commit()
    except IntegrityError:  # dos altas simultáneas (el índice por lower(name))
        await db.rollback()
        raise _duplicate()
    return technology


async def update_technology(db, id_technology: int, data: TechnologyUpdate) -> Technology:
    technology = await get_technology(db, id_technology)
    changes = data.model_fields_set
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No fields to update")

    if "name" in changes and data.name.lower() != technology.name.lower():
        if await _name_taken(db, data.name, exclude_id=id_technology):
            raise _duplicate()
    for field in changes:
        setattr(technology, field, getattr(data, field))
    db.add(technology)
    try:
        await db.commit()
    except IntegrityError:  # dos cambios simultáneos al mismo nombre
        await db.rollback()
        raise _duplicate()
    return technology


async def delete_technology(db, id_technology: int) -> None:
    technology = await get_technology(db, id_technology)
    try:
        await db.delete(technology)
        await db.commit()
    except IntegrityError:  # hay proyectos vinculados, la FK lo impide (RESTRICT)
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Technology is in use by a project and cannot be deleted",
        )


async def list_technologies(
    db, *, q: str | None, limit: int, offset: int
) -> tuple[list[Technology], int]:
    conditions = []
    if q:
        conditions.append(col(Technology.name).ilike(f"%{q.strip()}%"))
    total = (
        await db.exec(select(func.count()).select_from(Technology).where(*conditions))
    ).one()
    items = (
        await db.exec(
            select(Technology)
            .where(*conditions)
            .order_by(col(Technology.name), col(Technology.id_technology))
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(items), total
