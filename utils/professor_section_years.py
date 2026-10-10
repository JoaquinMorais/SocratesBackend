from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from models import Professor, ProfessorSectionYear, Section, SectionYear, User
from schemas.professor_section_year import (
    ProfessorSectionYearCreate,
    ProfessorSectionYearPublic,
    ProfessorSectionYearUpdate,
)
from utils.section_years import get_section_year


def to_public(
    ps: ProfessorSectionYear,
    professor: Professor | None = None,
    section_year: SectionYear | None = None,
) -> ProfessorSectionYearPublic:
    professor = professor or ps.professor
    sy = section_year or ps.section_year
    return ProfessorSectionYearPublic(
        id_professor_section_year=ps.id_professor_section_year,
        id_professor=professor.id_professor,
        professor_first_name=professor.user.first_name,
        professor_last_name=professor.user.last_name,
        id_section_year=sy.id_section_year,
        year=sy.year,
        id_section=sy.id_section,
        section_name=sy.section.name,
    )


def _duplicate() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT, "This professor is already assigned to that section year"
    )


async def _get_professor(db, id_professor: int) -> Professor:
    professor = await db.get(Professor, id_professor)
    if not professor:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Professor not found")
    return professor


async def get_assignment(db, id_assignment: int) -> ProfessorSectionYear:
    ps = await db.get(ProfessorSectionYear, id_assignment)
    if not ps:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    return ps


async def _pair_taken(
    db, id_professor: int, id_section_year: int, exclude_id: int | None = None
) -> bool:
    stmt = select(ProfessorSectionYear.id_professor_section_year).where(
        ProfessorSectionYear.id_professor == id_professor,
        ProfessorSectionYear.id_section_year == id_section_year,
    )
    if exclude_id is not None:
        stmt = stmt.where(ProfessorSectionYear.id_professor_section_year != exclude_id)
    return (await db.exec(stmt)).first() is not None


async def create_assignment(
    db, data: ProfessorSectionYearCreate
) -> ProfessorSectionYearPublic:
    professor = await _get_professor(db, data.id_professor)
    sy = await get_section_year(db, data.id_section_year)
    if await _pair_taken(db, data.id_professor, data.id_section_year):
        raise _duplicate()

    ps = ProfessorSectionYear(professor=professor, section_year=sy)
    db.add(ps)
    try:
        await db.commit()
    except IntegrityError:  # dos altas simultáneas con el mismo par
        await db.rollback()
        raise _duplicate()
    return to_public(ps, professor, sy)


async def update_assignment(
    db, id_assignment: int, data: ProfessorSectionYearUpdate
) -> ProfessorSectionYearPublic:
    ps = await get_assignment(db, id_assignment)
    changes = data.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No fields to update")

    id_professor = changes.get("id_professor", ps.id_professor)
    id_section_year = changes.get("id_section_year", ps.id_section_year)
    professor = await _get_professor(db, id_professor)
    sy = await get_section_year(db, id_section_year)

    if id_professor == ps.id_professor and id_section_year == ps.id_section_year:
        return to_public(ps, professor, sy)
    if await _pair_taken(db, id_professor, id_section_year, exclude_id=id_assignment):
        raise _duplicate()

    ps.professor = professor
    ps.section_year = sy
    db.add(ps)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise _duplicate()
    return to_public(ps, professor, sy)


async def delete_assignment(db, id_assignment: int) -> None:
    ps = await get_assignment(db, id_assignment)
    await db.delete(ps)
    await db.commit()


async def list_assignments(
    db,
    *,
    id_professor: int | None,
    id_section_year: int | None,
    year: int | None,
    id_section: int | None,
    limit: int,
    offset: int,
) -> tuple[list[ProfessorSectionYear], int]:
    conditions = []
    if id_professor is not None:
        conditions.append(ProfessorSectionYear.id_professor == id_professor)
    if id_section_year is not None:
        conditions.append(ProfessorSectionYear.id_section_year == id_section_year)
    if year is not None:
        conditions.append(SectionYear.year == year)
    if id_section is not None:
        conditions.append(SectionYear.id_section == id_section)

    on_section_year = SectionYear.id_section_year == ProfessorSectionYear.id_section_year
    total = (
        await db.exec(
            select(func.count())
            .select_from(ProfessorSectionYear)
            .join(SectionYear, on_section_year)
            .where(*conditions)
        )
    ).one()
    items = (
        await db.exec(
            select(ProfessorSectionYear)
            .join(SectionYear, on_section_year)
            .join(Section, Section.id_section == SectionYear.id_section)
            .join(Professor, Professor.id_professor == ProfessorSectionYear.id_professor)
            .join(User, User.id_user == Professor.id_professor)
            .where(*conditions)
            .order_by(
                col(SectionYear.year).desc(),
                col(Section.name),
                col(User.last_name),
                col(User.first_name),
                col(ProfessorSectionYear.id_professor_section_year),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(items), total