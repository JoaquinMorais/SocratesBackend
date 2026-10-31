from fastapi import HTTPException, status
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from models import (
    Calendar,
    Project,
    Section,
    SectionYear,
    Status,
    StudentProject,
    StudentSectionYear,
)
from models.state import MEMBER_CODES
from models.state.student_section_year import (
    ATTENDING,
    FINISHED_APPROVED,
    FINISHED_FAILED,
    REGISTERED,
)
from utils.deliveries import has_delivery_data_for_section_year
from schemas.section_year import (
    SectionYearCreate,
    SectionYearPublic,
    SectionYearSettingsUpdate,
    SectionYearUpdate,
)


def to_public(sy: SectionYear, section: Section | None = None) -> SectionYearPublic:
    section = section or sy.section
    return SectionYearPublic(
        id_section_year=sy.id_section_year,
        year=sy.year,
        id_section=section.id_section,
        section_name=section.name,
        min_students=sy.min_students,
        max_students=sy.max_students,
        allow_project_joins=sy.allow_project_joins,
    )


def _validate_range(min_students: int, max_students: int) -> None:
    if max_students < min_students:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "max_students must be greater than or equal to min_students",
        )


def _duplicate() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT, "This section already exists for that year"
    )


def _duplicate_student_year() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        "Some students already have a section year for that year",
    )


def _constraint_name(exc: IntegrityError) -> str:
    """Nombre de la restricción violada (asyncpg la expone de formas distintas)."""
    orig = exc.orig
    for candidate in (getattr(orig, "diag", None), orig, getattr(orig, "__cause__", None)):
        name = getattr(candidate, "constraint_name", None)
        if name:
            return name
    return ""




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


async def _students_with_other_year(
    db, id_section_year: int, new_year: int
) -> bool:
    """Si algún alumno inscripto acá ya tiene otra inscripción en el año nuevo."""
    enrolled = select(StudentSectionYear.id_student).where(
        StudentSectionYear.id_section_year == id_section_year,
        StudentSectionYear.state == REGISTERED,
    )
    found = (
        await db.exec(
            select(StudentSectionYear.id_student_section_year)
            .where(
                StudentSectionYear.year == new_year,
                StudentSectionYear.id_section_year != id_section_year,
                StudentSectionYear.id_student.in_(enrolled),
                StudentSectionYear.state == REGISTERED,
            )
            .limit(1)
        )
    ).first()
    return found is not None


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
    _validate_range(data.min_students, data.max_students)

    sy = SectionYear(
        year=data.year,
        id_section=data.id_section,
        min_students=data.min_students,
        max_students=data.max_students,
        allow_project_joins=data.allow_project_joins,
    )
    db.add(sy)
    try:
        await db.flush()  # obtiene id_section_year
        db.add(Calendar(id_section_year=sy.id_section_year))
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

    min_students = changes.get("min_students", sy.min_students)
    max_students = changes.get("max_students", sy.max_students)
    _validate_range(min_students, max_students)

    year = changes.get("year", sy.year)
    id_section = changes.get("id_section", sy.id_section)
    section = await _get_section(db, id_section)

    if (year, id_section) != (sy.year, sy.id_section):
        if await _combination_taken(db, year, id_section, exclude_id=id_section_year):
            raise _duplicate()

    year_changed = year != sy.year
    if year_changed and await _students_with_other_year(db, id_section_year, year):
        raise _duplicate_student_year()

    sy.year = year
    sy.section = section
    sy.min_students = min_students
    sy.max_students = max_students
    sy.allow_project_joins = changes.get("allow_project_joins", sy.allow_project_joins)
    db.add(sy)
    if year_changed:
        # mantener sincronizada la copia del año que usa la restricción única
        await db.exec(
            update(StudentSectionYear)
            .where(StudentSectionYear.id_section_year == id_section_year)
            .values(year=year)
        )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if "student_section_year_registered" in _constraint_name(exc):
            raise _duplicate_student_year()
        raise _duplicate()
    return to_public(sy, section)


async def update_section_year_settings(
    db, id_section_year: int, data: SectionYearSettingsUpdate
) -> SectionYearPublic:
    sy = await get_section_year(db, id_section_year)
    sy.allow_project_joins = data.allow_project_joins
    db.add(sy)
    await db.commit()
    return to_public(sy)


async def delete_section_year(db, id_section_year: int) -> None:
    sy = await get_section_year(db, id_section_year)
    if await has_delivery_data_for_section_year(db, id_section_year):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Section year has delivery data and cannot be deleted",
        )
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

async def can_view_section_year(db, user, access, id_section_year: int) -> bool:
    """Si el usuario puede ver el calendario de ese curso lectivo.

    Pueden verlo el super admin, un profesor asignado a ese curso lectivo y los
    alumnos del curso: los que tienen una cursada (`attending` o `finished_*`) o
    son miembros (`active`/`finished`) de alguno de sus proyectos. La inscripción
    (`registered`) y las cursadas abandonadas no alcanzan.
    """
    if access.can_manage(id_section_year):
        return True
    if not user.student:
        return False

    cursada = (
        await db.exec(
            select(StudentSectionYear.id_student_section_year)
            .where(
                StudentSectionYear.id_student == user.id_user,
                StudentSectionYear.id_section_year == id_section_year,
                StudentSectionYear.state.in_(
                    (ATTENDING, FINISHED_APPROVED, FINISHED_FAILED)
                ),
            )
            .limit(1)
        )
    ).first()
    if cursada is not None:
        return True

    membership = (
        await db.exec(
            select(StudentProject.id_student_project)
            .join(Project, Project.id_project == StudentProject.id_project)
            .join(Status, Status.id_status == StudentProject.id_status)
            .where(
                StudentProject.id_student == user.id_user,
                Project.id_section_year == id_section_year,
                Status.code.in_(MEMBER_CODES),
            )
            .limit(1)
        )
    ).first()
    return membership is not None


async def require_view_section_year(db, user, access, id_section_year: int) -> None:
    if not await can_view_section_year(db, user, access, id_section_year):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You cannot view this section year"
        )


async def ensure_calendar(db, id_section_year: int) -> Calendar:
    """Devuelve el calendario del curso lectivo; lo crea si todavía no existe.

    Es idempotente y tolera carreras: si dos requests lo crean a la vez, la
    segunda relee el existente.
    """
    calendar = (
        await db.exec(
            select(Calendar).where(Calendar.id_section_year == id_section_year)
        )
    ).first()
    if calendar is not None:
        return calendar

    await get_section_year(db, id_section_year)  # 404 si el curso no existe
    calendar = Calendar(id_section_year=id_section_year)
    db.add(calendar)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        calendar = (
            await db.exec(
                select(Calendar).where(
                    Calendar.id_section_year == id_section_year
                )
            )
        ).first()
        if calendar is None:
            raise
    return calendar
