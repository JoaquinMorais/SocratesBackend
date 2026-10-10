from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from models import Section, SectionYear
from schemas.section_year import (
    SectionYearCreate,
    SectionYearPublic,
    SectionYearUpdate,
)


def to_public(sy: SectionYear, section: Section | None = None) -> SectionYearPublic:
    section = section or sy.section
    return SectionYearPublic(
        id_section_year=sy.id_section_year,
        year=sy.year,
        id_section=section.id_section,
        section_name=section.name,
    )


def _duplicate() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT, "This section already exists for that year"
    )


async def _get_section(db, id_section: int) -> Section:
    section = await db.get(Section, id_section)
    if not section:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Section not found")
    return section


async def get_section_year(db, id_section_year: int) -> SectionYear:
    sy = await db.get(SectionYear, id_section_year)
    if not sy:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Section year not found")
    return sy


async def _combination_taken(
    db, year: int, id_section: int, exclude_id: int | None = None
) -> bool:
    stmt = select(SectionYear.id_section_year).where(
        SectionYear.year == year, SectionYear.id_section == id_section
    )
    if exclude_id is not None:
        stmt = stmt.where(SectionYear.id_section_year != exclude_id)
    return (await db.exec(stmt)).first() is not None


async def create_section_year(db, data: SectionYearCreate) -> SectionYearPublic:
    section = await _get_section(db, data.id_section)
    if await _combination_taken(db, data.year, data.id_section):
        raise _duplicate()

    sy = SectionYear(year=data.year, id_section=data.id_section)
    db.add(sy)
    try:
        await db.commit()
    except IntegrityError:  # dos altas simultáneas con la misma combinación
        await db.rollback()
        raise _duplicate()
    return to_public(sy, section)


async def update_section_year(
    db, id_section_year: int, data: SectionYearUpdate
) -> SectionYearPublic:
    sy = await get_section_year(db, id_section_year)
    changes = data.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No fields to update")

    year = changes.get("year", sy.year)
    id_section = changes.get("id_section", sy.id_section)
    section = await _get_section(db, id_section)

    if year == sy.year and id_section == sy.id_section:
        return to_public(sy, section)
    if await _combination_taken(db, year, id_section, exclude_id=id_section_year):
        raise _duplicate()

    sy.year = year
    sy.section = section
    db.add(sy)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise _duplicate()
    return to_public(sy, section)


async def delete_section_year(db, id_section_year: int) -> None:
    sy = await get_section_year(db, id_section_year)
    try:
        await db.delete(sy)
        await db.commit()
    except IntegrityError:  # cuando haya alumnos asociados, la FK lo impide
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Section year is in use and cannot be deleted"
        )


async def list_section_years(
    db, *, year: int | None, id_section: int | None, limit: int, offset: int
) -> tuple[list[SectionYear], int]:
    conditions = []
    if year is not None:
        conditions.append(SectionYear.year == year)
    if id_section is not None:
        conditions.append(SectionYear.id_section == id_section)

    total = (
        await db.exec(select(func.count()).select_from(SectionYear).where(*conditions))
    ).one()
    items = (
        await db.exec(
            select(SectionYear)
            .join(Section, Section.id_section == SectionYear.id_section)
            .where(*conditions)
            .order_by(
                col(SectionYear.year).desc(),
                col(Section.name),
                col(SectionYear.id_section_year),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(items), total