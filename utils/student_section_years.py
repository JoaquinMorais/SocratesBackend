from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from models import Section, SectionYear, Student, StudentSectionYear, User
from models.student_section_year import (
    ABANDONED,
    ATTENDING,
    FINISHED_APPROVED,
    FINISHED_FAILED,
    REGISTERED,
)
from schemas.student_section_year import (
    StudentSectionYearCreate,
    StudentSectionYearPublic,
    StudentSectionYearUpdate,
)
from utils.section_years import get_section_year


def to_public(
    ssy: StudentSectionYear,
    student: Student | None = None,
    section_year: SectionYear | None = None,
) -> StudentSectionYearPublic:
    student = student or ssy.student
    sy = section_year or ssy.section_year
    user = student.user
    return StudentSectionYearPublic(
        id_student_section_year=ssy.id_student_section_year,
        id_student=student.id_student,
        state=ssy.state,
        student_first_name=user.first_name,
        student_last_name=user.last_name,
        student_legajo=user.legajo,
        id_section_year=sy.id_section_year,
        year=sy.year,
        id_section=sy.id_section,
        section_name=sy.section.name,
    )


def _duplicate_registration() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        "This student already has a registration for that year",
    )


def _managed_automatically() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        "Cursadas are managed automatically by project membership",
    )


def _constraint_name(exc: IntegrityError) -> str:
    """Nombre de la restricción violada (asyncpg la expone de formas distintas)."""
    orig = exc.orig
    for candidate in (
        getattr(orig, "diag", None),
        orig,
        getattr(orig, "__cause__", None),
    ):
        name = getattr(candidate, "constraint_name", None)
        if name:
            return name
    return ""


def _integrity_conflict(exc: IntegrityError) -> HTTPException:
    if "student_section_year_registered" in _constraint_name(exc):
        return _duplicate_registration()
    return HTTPException(
        status.HTTP_409_CONFLICT, "The section year link conflicts with another row"
    )


async def _get_student(db, id_student: int) -> Student:
    student = await db.get(Student, id_student)
    if not student:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    return student


async def get_enrollment(db, id_enrollment: int) -> StudentSectionYear:
    ssy = await db.get(StudentSectionYear, id_enrollment)
    if not ssy:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Enrollment not found")
    return ssy


async def _registration_year_taken(
    db, id_student: int, year: int, exclude_id: int | None = None
) -> bool:
    stmt = select(StudentSectionYear.id_student_section_year).where(
        StudentSectionYear.id_student == id_student,
        StudentSectionYear.year == year,
        StudentSectionYear.state == REGISTERED,
    )
    if exclude_id is not None:
        stmt = stmt.where(StudentSectionYear.id_student_section_year != exclude_id)
    return (await db.exec(stmt)).first() is not None


async def create_enrollment(
    db, data: StudentSectionYearCreate
) -> StudentSectionYearPublic:
    student = await _get_student(db, data.id_student)
    sy = await get_section_year(db, data.id_section_year)
    if await _registration_year_taken(db, data.id_student, sy.year):
        raise _duplicate_registration()

    ssy = StudentSectionYear(
        student=student, section_year=sy, year=sy.year, state=REGISTERED
    )
    db.add(ssy)
    try:
        await db.commit()
    except IntegrityError as exc:  # altas simultáneas de la misma inscripción
        await db.rollback()
        raise _integrity_conflict(exc)
    return to_public(ssy, student, sy)


async def update_enrollment(
    db, id_enrollment: int, data: StudentSectionYearUpdate
) -> StudentSectionYearPublic:
    ssy = await get_enrollment(db, id_enrollment)
    if ssy.state != REGISTERED:
        raise _managed_automatically()

    changes = data.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No fields to update")

    id_student = changes.get("id_student", ssy.id_student)
    id_section_year = changes.get("id_section_year", ssy.id_section_year)
    student = await _get_student(db, id_student)
    sy = await get_section_year(db, id_section_year)

    if id_student == ssy.id_student and id_section_year == ssy.id_section_year:
        return to_public(ssy, student, sy)
    if await _registration_year_taken(
        db, id_student, sy.year, exclude_id=id_enrollment
    ):
        raise _duplicate_registration()

    ssy.student = student
    ssy.section_year = sy
    ssy.year = sy.year
    db.add(ssy)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise _integrity_conflict(exc)
    return to_public(ssy, student, sy)


async def delete_enrollment(db, id_enrollment: int) -> None:
    ssy = await get_enrollment(db, id_enrollment)
    if ssy.state != REGISTERED:
        raise _managed_automatically()
    await db.delete(ssy)
    await db.commit()


async def list_enrollments(
    db,
    *,
    id_student: int | None,
    id_section_year: int | None,
    year: int | None,
    id_section: int | None,
    state: str | None,
    limit: int,
    offset: int,
) -> tuple[list[StudentSectionYear], int]:
    conditions = []
    if id_student is not None:
        conditions.append(StudentSectionYear.id_student == id_student)
    if id_section_year is not None:
        conditions.append(StudentSectionYear.id_section_year == id_section_year)
    if year is not None:
        conditions.append(SectionYear.year == year)
    if id_section is not None:
        conditions.append(SectionYear.id_section == id_section)
    if state is not None:
        conditions.append(StudentSectionYear.state == state)

    on_section_year = (
        SectionYear.id_section_year == StudentSectionYear.id_section_year
    )
    total = (
        await db.exec(
            select(func.count())
            .select_from(StudentSectionYear)
            .join(SectionYear, on_section_year)
            .where(*conditions)
        )
    ).one()
    items = (
        await db.exec(
            select(StudentSectionYear)
            .join(SectionYear, on_section_year)
            .join(Section, Section.id_section == SectionYear.id_section)
            .join(Student, Student.id_student == StudentSectionYear.id_student)
            .join(User, User.id_user == Student.id_student)
            .where(*conditions)
            .order_by(
                col(SectionYear.year).desc(),
                col(Section.name),
                col(User.last_name),
                col(User.first_name),
                col(StudentSectionYear.id_student_section_year),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(items), total


# ----------------------------------------------------------------------
# Cursadas (administradas por la membresía al proyecto)
# ----------------------------------------------------------------------
async def student_current_row(db, id_student: int) -> StudentSectionYear | None:
    """La fila que define el año actual del alumno.

    Prioridad: cursada `attending`; si no hay, la última `finished_*`; si no, la
    última inscripción `registered`. Las cursadas `abandoned` no cuentan.
    """
    rows = (
        await db.exec(
            select(StudentSectionYear).where(
                StudentSectionYear.id_student == id_student
            )
        )
    ).all()

    attending = [row for row in rows if row.state == ATTENDING]
    if attending:
        return attending[0]

    finished = [
        row
        for row in rows
        if row.state in (FINISHED_APPROVED, FINISHED_FAILED)
    ]
    if finished:
        return max(finished, key=lambda row: (row.year, row.id_student_section_year))

    registered = [row for row in rows if row.state == REGISTERED]
    if registered:
        return max(registered, key=lambda row: (row.year, row.id_student_section_year))
    return None


async def student_current_year(db, id_student: int) -> int | None:
    row = await student_current_row(db, id_student)
    return row.year if row is not None else None


async def validate_project_year(db, id_student: int, project_year: int) -> None:
    """El proyecto debe ser del año actual del alumno."""
    current_year = await student_current_year(db, id_student)
    if current_year is not None and current_year != project_year:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The project must be in the student's current year",
        )


async def _cursada_row(db, id_student: int, id_section_year: int):
    return (
        await db.exec(
            select(StudentSectionYear).where(
                StudentSectionYear.id_student == id_student,
                StudentSectionYear.id_section_year == id_section_year,
                StudentSectionYear.state != REGISTERED,
            )
        )
    ).first()


async def _current_attending(db, id_student: int):
    return (
        await db.exec(
            select(StudentSectionYear).where(
                StudentSectionYear.id_student == id_student,
                StudentSectionYear.state == ATTENDING,
            )
        )
    ).first()


async def ensure_attending(
    db,
    id_student: int,
    id_section_year: int,
    year: int,
    *,
    allow_project_joins: bool = False,
) -> StudentSectionYear:
    """Crea o reactiva la cursada del alumno en el curso lectivo del proyecto."""
    row = await _cursada_row(db, id_student, id_section_year)
    current = await _current_attending(db, id_student)

    if row is not None:
        if row.state == FINISHED_APPROVED:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This section year is already finished",
            )
        if row.state == FINISHED_FAILED and not allow_project_joins:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This section year is already finished",
            )
        row.state = ATTENDING
        row.year = year
        db.add(row)
    else:
        row = StudentSectionYear(
            id_student=id_student,
            id_section_year=id_section_year,
            year=year,
            state=ATTENDING,
        )
        db.add(row)

    if current is not None and current is not row:
        current.state = ABANDONED
        db.add(current)

    await db.flush()
    return row


async def close_attending(
    db, id_student: int, id_section_year: int, new_state: str
) -> None:
    """Cierra la cursada actual del alumno en un curso lectivo."""
    row = (
        await db.exec(
            select(StudentSectionYear).where(
                StudentSectionYear.id_student == id_student,
                StudentSectionYear.id_section_year == id_section_year,
                StudentSectionYear.state == ATTENDING,
            )
        )
    ).first()
    if row is not None:
        row.state = new_state
        db.add(row)


async def finish_attending(
    db, id_student: int, id_section_year: int, *, approved: bool
) -> None:
    await close_attending(
        db,
        id_student,
        id_section_year,
        FINISHED_APPROVED if approved else FINISHED_FAILED,
    )
