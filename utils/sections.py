from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from models import Section
from schemas.section import SectionCreate, SectionPublic, SectionUpdate


def to_public(section: Section) -> SectionPublic:
    return SectionPublic(id_section=section.id_section, name=section.name)


def _duplicate() -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, "A section with this name already exists")


async def get_section(db, id_section: int) -> Section:
    section = await db.get(Section, id_section)
    if not section:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Section not found")
    return section


async def _name_taken(db, name: str, exclude_id: int | None = None) -> bool:
    stmt = select(Section.id_section).where(Section.name == name)
    if exclude_id is not None:
        stmt = stmt.where(Section.id_section != exclude_id)
    return (await db.exec(stmt)).first() is not None


async def create_section(db, data: SectionCreate) -> Section:
    if await _name_taken(db, data.name):
        raise _duplicate()
    section = Section(name=data.name)
    db.add(section)
    try:
        await db.commit()
    except IntegrityError:  # dos altas simultáneas con el mismo nombre
        await db.rollback()
        raise _duplicate()
    return section


async def update_section(db, id_section: int, data: SectionUpdate) -> Section:
    section = await get_section(db, id_section)
    if data.name == section.name:
        return section
    if await _name_taken(db, data.name, exclude_id=id_section):
        raise _duplicate()
    section.name = data.name
    db.add(section)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise _duplicate()
    return section


async def delete_section(db, id_section: int) -> None:
    section = await get_section(db, id_section)
    try:
        await db.delete(section)
        await db.commit()
    except IntegrityError:  # cuando haya alumnos asociados, la FK lo impide
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Section is in use and cannot be deleted")


async def list_sections(db, *, q: str | None, limit: int, offset: int) -> tuple[list[Section], int]:
    conditions = []
    if q:
        conditions.append(col(Section.name).ilike(f"%{q.strip()}%"))
    total = (
        await db.exec(select(func.count()).select_from(Section).where(*conditions))
    ).one()
    items = (
        await db.exec(
            select(Section)
            .where(*conditions)
            .order_by(col(Section.name))
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(items), total