from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from models import Section, SectionYear, Student, StudentSectionYear, User
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
        student_first_name=user.first_name,
        student_last_name=user.last_name,
        student_legajo=user.legajo,
        id_section_year=sy.id_section_year,
        year=sy.year,
        id_section=sy.id_section,
        section_name=sy.section.name,
    )


def _duplicate() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        "This student is already enrolled in that section year",
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


async def _pair_taken(
    db, id_student: int, id_section_year: int, exclude_id: int | None = None
) -> bool:
    stmt = select(StudentSectionYear.id_student_section_year).where(
        StudentSectionYear.id_student == id_student,
        StudentSectionYear.id_section_year == id_section_year,
    )
    if exclude_id is not None:
        stmt = stmt.where(StudentSectionYear.id_student_section_year != exclude_id)
    return (await db.exec(stmt)).first() is not None


async def create_enrollment(
    db, data: StudentSectionYearCreate
) -> StudentSectionYearPublic:
    student = await _get_student(db, data.id_student)
    sy = await get_section_year(db, data.id_section_year)
    if await _pair_taken(db, data.id_student, data.id_section_year):
        raise _duplicate()

    ssy = StudentSectionYear(student=student, section_year=sy)
    db.add(ssy)
    try:
        await db.commit()
    except IntegrityError:  # dos altas simultáneas con el mismo par
        await db.rollback()
        raise _duplicate()
    return to_public(ssy, student, sy)


async def update_enrollment(
    db, id_enrollment: int, data: StudentSectionYearUpdate
) -> StudentSectionYearPublic:
    ssy = await get_enrollment(db, id_enrollment)
    changes = data.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No fields to update")

    id_student = changes.get("id_student", ssy.id_student)
    id_section_year = changes.get("id_section_year", ssy.id_section_year)
    student = await _get_student(db, id_student)
    sy = await get_section_year(db, id_section_year)

    if id_student == ssy.id_student and id_section_year == ssy.id_section_year:
        return to_public(ssy, student, sy)
    if await _pair_taken(db, id_student, id_section_year, exclude_id=id_enrollment):
        raise _duplicate()

    ssy.student = student
    ssy.section_year = sy
    db.add(ssy)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise _duplicate()
    return to_public(ssy, student, sy)


async def delete_enrollment(db, id_enrollment: int) -> None:
    ssy = await get_enrollment(db, id_enrollment)
    await db.delete(ssy)
    await db.commit()


async def list_enrollments(
    db,
    *,
    id_student: int | None,
    id_section_year: int | None,
    year: int | None,
    id_section: int | None,
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
