import hmac
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from config.settings import settings
from models import (
    Attendance,
    AttendanceSession,
    Calendar,
    CalendarClass,
    Section,
    SectionYear,
    StudentSectionYear,
    User,
)
from models.student_section_year import (
    ATTENDING,
    FINISHED_APPROVED,
    FINISHED_FAILED,
)
from schemas.attendance import (
    AttendanceBulkResult,
    AttendancePublic,
    AttendanceSessionOpenedPublic,
    AttendanceSessionStatusPublic,
    AttendanceStudentPublic,
    ClassAttendancePublic,
    MyAttendanceItemPublic,
    MyAttendanceListPublic,
)
from utils.date_ranges import validate_optional_range
from utils.security import generate_otp, hash_otp

# Cursadas que se pueden ver en la lista histórica de una clase.
_LIST_CURSADA_STATES = (ATTENDING, FINISHED_APPROVED, FINISHED_FAILED)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _not_found_class() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Calendar class not found")


def _not_found_session() -> HTTPException:
    return HTTPException(
        status.HTTP_404_NOT_FOUND, "Attendance session not found"
    )


def _not_found_attendance() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Attendance not found")


def _not_found_enrollment() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Student enrollment not found")


def _forbidden() -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Only a professor of this section year or a super admin can do this",
    )


def _closed() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT, "Attendance is closed"
    )


def _invalid_code() -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid attendance code"
    )


def _not_enrolled() -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN, "You are not attending this section year"
    )


def _foreign_enrollment() -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Student enrollment does not belong to this section year",
    )


def _is_open(session: AttendanceSession) -> bool:
    return session.closed_at is None and session.expires_at > _now()


def session_status(
    session: AttendanceSession | None,
) -> AttendanceSessionStatusPublic | None:
    if session is None:
        return None
    return AttendanceSessionStatusPublic(
        id_attendance_session=session.id_attendance_session,
        open=_is_open(session),
        opened_at=session.opened_at,
        expires_at=session.expires_at,
        closed_at=session.closed_at,
    )


def to_public(
    attendance: Attendance, enrollment: StudentSectionYear | None = None
) -> AttendancePublic:
    enrollment = enrollment or attendance.student_section_year
    return AttendancePublic(
        id_attendance=attendance.id_attendance,
        id_calendar_class=attendance.id_calendar_class,
        id_student_section_year=enrollment.id_student_section_year,
        id_student=enrollment.id_student,
        id_section_year=enrollment.id_section_year,
        method=attendance.method,
        recorded_at=attendance.recorded_at,
    )


async def _get_class(db, id_calendar_class: int) -> CalendarClass:
    calendar_class = await db.get(CalendarClass, id_calendar_class)
    if not calendar_class:
        raise _not_found_class()
    return calendar_class


async def _get_session(db, id_calendar_class: int) -> AttendanceSession | None:
    return (
        await db.exec(
            select(AttendanceSession).where(
                AttendanceSession.id_calendar_class == id_calendar_class
            )
        )
    ).first()


async def _get_attendance(
    db, id_student_section_year: int, id_calendar_class: int
) -> Attendance | None:
    return (
        await db.exec(
            select(Attendance).where(
                Attendance.id_student_section_year == id_student_section_year,
                Attendance.id_calendar_class == id_calendar_class,
            )
        )
    ).first()


async def _get_enrollment(
    db, id_student: int, id_section_year: int
) -> StudentSectionYear:
    enrollment = (
        await db.exec(
            select(StudentSectionYear).where(
                StudentSectionYear.id_student == id_student,
                StudentSectionYear.id_section_year == id_section_year,
                StudentSectionYear.state == ATTENDING,
            )
        )
    ).first()
    if not enrollment:
        raise _not_enrolled()
    return enrollment


async def open_attendance(
    db, access, id_calendar_class: int
) -> AttendanceSessionOpenedPublic:
    calendar_class = await _get_class(db, id_calendar_class)
    if not access.can_manage(calendar_class.calendar.id_section_year):
        raise _forbidden()

    now = _now()
    code = generate_otp()
    expires_at = now + timedelta(minutes=settings.ATTENDANCE_CODE_MINUTES)
    session = await _get_session(db, id_calendar_class)
    if session is None:
        session = AttendanceSession(
            id_calendar_class=id_calendar_class,
            code_hash=hash_otp(code),
            opened_at=now,
            expires_at=expires_at,
        )
    else:
        session.code_hash = hash_otp(code)
        session.opened_at = now
        session.expires_at = expires_at
        session.closed_at = None
    db.add(session)

    try:
        await db.commit()
    except IntegrityError:  # dos aperturas simultáneas
        await db.rollback()
        session = await _get_session(db, id_calendar_class)
        if session is None:
            raise
        session.code_hash = hash_otp(code)
        session.opened_at = now
        session.expires_at = expires_at
        session.closed_at = None
        db.add(session)
        await db.commit()

    return AttendanceSessionOpenedPublic(
        id_attendance_session=session.id_attendance_session,
        id_calendar_class=id_calendar_class,
        code=code,
        expires_at=expires_at,
    )


async def close_attendance(db, access, id_calendar_class: int) -> None:
    calendar_class = await _get_class(db, id_calendar_class)
    if not access.can_manage(calendar_class.calendar.id_section_year):
        raise _forbidden()
    session = await _get_session(db, id_calendar_class)
    if session is None:
        raise _not_found_session()
    if session.closed_at is None:
        session.closed_at = _now()
        db.add(session)
        await db.commit()


async def check_in(
    db, student, id_calendar_class: int, code: str
) -> AttendancePublic:
    calendar_class = await _get_class(db, id_calendar_class)
    enrollment = await _get_enrollment(
        db,
        student.id_student,
        calendar_class.calendar.id_section_year,
    )

    session = await _get_session(db, id_calendar_class)
    if session is None or not _is_open(session):
        raise _closed()
    if not hmac.compare_digest(session.code_hash, hash_otp(code)):
        raise _invalid_code()

    existing = await _get_attendance(
        db, enrollment.id_student_section_year, id_calendar_class
    )
    if existing is not None:
        return to_public(existing, enrollment)

    attendance = Attendance(
        id_student_section_year=enrollment.id_student_section_year,
        id_calendar_class=id_calendar_class,
        method="code",
    )
    db.add(attendance)
    try:
        await db.commit()
    except IntegrityError:  # dos check-ins simultáneos: idempotente
        await db.rollback()
        existing = await _get_attendance(
            db, enrollment.id_student_section_year, id_calendar_class
        )
        if existing is None:
            raise
        return to_public(existing, enrollment)
    return to_public(attendance, enrollment)


async def list_attendance(db, access, id_calendar_class: int) -> ClassAttendancePublic:
    calendar_class = await _get_class(db, id_calendar_class)
    if not access.can_manage(calendar_class.calendar.id_section_year):
        raise _forbidden()

    rows = (
        await db.exec(
            select(StudentSectionYear, User)
            .join(User, User.id_user == StudentSectionYear.id_student)
            .where(
                StudentSectionYear.id_section_year
                == calendar_class.calendar.id_section_year,
                StudentSectionYear.state.in_(_LIST_CURSADA_STATES),
            )
            .order_by(
                col(User.last_name),
                col(User.first_name),
                col(StudentSectionYear.id_student_section_year),
            )
        )
    ).all()
    attendance_rows = (
        await db.exec(
            select(Attendance).where(
                Attendance.id_calendar_class == id_calendar_class
            )
        )
    ).all()
    by_enrollment = {
        row.id_student_section_year: row for row in attendance_rows
    }

    items = []
    for enrollment, user in rows:
        attendance = by_enrollment.get(enrollment.id_student_section_year)
        items.append(
            AttendanceStudentPublic(
                id_student_section_year=enrollment.id_student_section_year,
                id_student=enrollment.id_student,
                first_name=user.first_name,
                last_name=user.last_name,
                legajo=user.legajo,
                state=enrollment.state,
                present=attendance is not None,
                method=attendance.method if attendance else None,
                recorded_at=attendance.recorded_at if attendance else None,
            )
        )

    return ClassAttendancePublic(
        session=session_status(await _get_session(db, id_calendar_class)),
        items=items,
    )


async def mark_manual(
    db, access, id_calendar_class: int, id_student_section_year: int
) -> AttendancePublic:
    calendar_class = await _get_class(db, id_calendar_class)
    if not access.can_manage(calendar_class.calendar.id_section_year):
        raise _forbidden()

    enrollment = await db.get(StudentSectionYear, id_student_section_year)
    if not enrollment:
        raise _not_found_enrollment()
    if enrollment.id_section_year != calendar_class.calendar.id_section_year:
        raise _foreign_enrollment()
    if enrollment.state != ATTENDING:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Student is not attending this section year",
        )

    existing = await _get_attendance(db, id_student_section_year, id_calendar_class)
    if existing is not None:
        return to_public(existing, enrollment)

    attendance = Attendance(
        id_student_section_year=id_student_section_year,
        id_calendar_class=id_calendar_class,
        method="manual",
    )
    db.add(attendance)
    try:
        await db.commit()
    except IntegrityError:  # idempotente ante carreras
        await db.rollback()
        existing = await _get_attendance(
            db, id_student_section_year, id_calendar_class
        )
        if existing is None:
            raise
        return to_public(existing, enrollment)
    return to_public(attendance, enrollment)


async def mark_manual_bulk(
    db, access, id_calendar_class: int, id_students: list[int]
) -> AttendanceBulkResult:
    """Marca presentes a varios alumnos a mano (todo o nada e idempotente)."""
    calendar_class = await _get_class(db, id_calendar_class)
    id_section_year = calendar_class.calendar.id_section_year
    if not access.can_manage(id_section_year):
        raise _forbidden()

    # Deduplicar conservando el orden y la fila original de cada alumno.
    unique: list[int] = []
    first_row: dict[int, int] = {}
    for index, id_student in enumerate(id_students, start=1):
        if id_student not in first_row:
            first_row[id_student] = index
            unique.append(id_student)

    users = set(
        (
            await db.exec(
                select(User.id_user).where(User.id_user.in_(unique))
            )
        ).all()
    )
    rows = (
        await db.exec(
            select(StudentSectionYear, User)
            .join(User, User.id_user == StudentSectionYear.id_student)
            .where(
                StudentSectionYear.id_student.in_(unique),
                StudentSectionYear.id_section_year == id_section_year,
                StudentSectionYear.state == ATTENDING,
            )
        )
    ).all()
    enrolled = {
        enrollment.id_student: (enrollment, user) for enrollment, user in rows
    }

    errors = []
    for id_student in unique:
        if id_student in enrolled:
            continue
        detail = (
            "Student not found"
            if id_student not in users
            else "Student is not attending this section year"
        )
        errors.append(
            {
                "row": first_row[id_student],
                "id_student": id_student,
                "detail": detail,
            }
        )
    if errors:
        errors.sort(key=lambda error: error["row"])
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=errors
        )

    enrollment_ids = [
        enrollment.id_student_section_year
        for enrollment, _ in enrolled.values()
    ]
    existing_rows = (
        await db.exec(
            select(Attendance).where(
                Attendance.id_calendar_class == id_calendar_class,
                Attendance.id_student_section_year.in_(enrollment_ids),
            )
        )
    ).all()
    existing = {
        row.id_student_section_year: row for row in existing_rows
    }

    ordered: list[tuple[Attendance, StudentSectionYear]] = []
    pending: list[Attendance] = []
    for id_student in unique:
        enrollment, _ = enrolled[id_student]
        attendance = existing.get(enrollment.id_student_section_year)
        if attendance is None:
            attendance = Attendance(
                id_student_section_year=enrollment.id_student_section_year,
                id_calendar_class=id_calendar_class,
                method="manual",
            )
            pending.append(attendance)
        ordered.append((attendance, enrollment))

    if pending:
        db.add_all(pending)
        try:
            await db.commit()
        except IntegrityError:  # el estado cambió mientras se guardaba
            await db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Attendance changed while saving; please retry",
            )

    return AttendanceBulkResult(
        requested=len(unique),
        created=len(pending),
        already_present=len(ordered) - len(pending),
        items=[
            to_public(attendance, enrollment)
            for attendance, enrollment in ordered
        ],
    )


async def unmark_manual(
    db, access, id_calendar_class: int, id_student_section_year: int
) -> None:
    calendar_class = await _get_class(db, id_calendar_class)
    if not access.can_manage(calendar_class.calendar.id_section_year):
        raise _forbidden()
    attendance = await _get_attendance(
        db, id_student_section_year, id_calendar_class
    )
    if attendance is None:
        raise _not_found_attendance()
    await db.delete(attendance)
    await db.commit()


async def list_my_attendance(
    db,
    student,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> MyAttendanceListPublic:
    validate_optional_range(from_date, to_date)

    enrollments = select(StudentSectionYear.id_student_section_year).where(
        StudentSectionYear.id_student == student.id_student
    )
    conditions = [Attendance.id_student_section_year.in_(enrollments)]
    if from_date is not None:
        conditions.append(CalendarClass.date >= from_date)
        conditions.append(CalendarClass.date <= to_date)

    rows = (
        await db.exec(
            select(Attendance, CalendarClass, SectionYear, Section)
            .join(
                CalendarClass,
                CalendarClass.id_calendar_class == Attendance.id_calendar_class,
            )
            .join(Calendar, Calendar.id_calendar == CalendarClass.id_calendar)
            .join(
                SectionYear,
                SectionYear.id_section_year == Calendar.id_section_year,
            )
            .join(Section, Section.id_section == SectionYear.id_section)
            .where(*conditions)
            .order_by(
                col(CalendarClass.date).desc(),
                col(CalendarClass.start_time).desc(),
                col(Attendance.id_attendance).desc(),
            )
        )
    ).all()

    return MyAttendanceListPublic(
        items=[
            MyAttendanceItemPublic(
                id_attendance=attendance.id_attendance,
                id_calendar_class=calendar_class.id_calendar_class,
                id_section_year=section_year.id_section_year,
                year=section_year.year,
                id_section=section.id_section,
                section_name=section.name,
                date=calendar_class.date,
                start_time=calendar_class.start_time,
                end_time=calendar_class.end_time,
                title=calendar_class.title,
                modality=calendar_class.modality,
                method=attendance.method,
                recorded_at=attendance.recorded_at,
            )
            for attendance, calendar_class, section_year, section in rows
        ]
    )
