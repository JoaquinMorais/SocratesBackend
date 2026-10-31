from datetime import date

from sqlalchemy import func
from sqlmodel import select

from models import (
    Attendance,
    AttendanceSession,
    Calendar,
    CalendarClass,
    StudentSectionYear,
)
from schemas.attendance import AttendanceStatsPublic


def _date_conditions(from_date: date | None, to_date: date | None) -> list:
    conditions = []
    if from_date is not None:
        conditions.append(CalendarClass.date >= from_date)
    if to_date is not None:
        conditions.append(CalendarClass.date <= to_date)
    return conditions


def _to_public(attended: int, total: int) -> AttendanceStatsPublic:
    return AttendanceStatsPublic(
        attended_classes=attended,
        total_classes=total,
        attendance_percentage=(
            round(attended * 100 / total, 2) if total else None
        ),
    )


async def session_counts(
    db,
    section_year_ids: set[int] | list[int],
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> dict[int, int]:
    """Clases con toma por curso lectivo (opcionalmente dentro de un rango)."""
    if not section_year_ids:
        return {}
    conditions = [Calendar.id_section_year.in_(list(section_year_ids))]
    conditions.extend(_date_conditions(from_date, to_date))
    rows = (
        await db.exec(
            select(
                Calendar.id_section_year,
                func.count(AttendanceSession.id_attendance_session),
            )
            .select_from(Calendar)
            .join(CalendarClass, CalendarClass.id_calendar == Calendar.id_calendar)
            .join(
                AttendanceSession,
                AttendanceSession.id_calendar_class
                == CalendarClass.id_calendar_class,
            )
            .where(*conditions)
            .group_by(Calendar.id_section_year)
        )
    ).all()
    return {section_year_id: count for section_year_id, count in rows}


async def attended_counts(
    db,
    cursada_ids: set[int] | list[int],
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> dict[int, int]:
    """Asistencias por cursada, contando solo clases que tienen toma."""
    if not cursada_ids:
        return {}
    conditions = [Attendance.id_student_section_year.in_(list(cursada_ids))]
    conditions.extend(_date_conditions(from_date, to_date))
    rows = (
        await db.exec(
            select(
                Attendance.id_student_section_year,
                func.count(Attendance.id_attendance),
            )
            .join(
                AttendanceSession,
                AttendanceSession.id_calendar_class == Attendance.id_calendar_class,
            )
            .join(
                CalendarClass,
                CalendarClass.id_calendar_class == Attendance.id_calendar_class,
            )
            .join(Calendar, Calendar.id_calendar == CalendarClass.id_calendar)
            .join(
                StudentSectionYear,
                StudentSectionYear.id_student_section_year
                == Attendance.id_student_section_year,
            )
            .where(
                *conditions,
                StudentSectionYear.id_section_year == Calendar.id_section_year,
            )
            .group_by(Attendance.id_student_section_year)
        )
    ).all()
    return {cursada_id: count for cursada_id, count in rows}


async def attendance_stats_for_cursadas(
    db,
    cursadas: list[StudentSectionYear],
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> dict[int, AttendanceStatsPublic]:
    """Estadísticas por fila de cursada, sin mezclar cursos lectivos."""
    cursadas = [row for row in cursadas if row is not None]
    if not cursadas:
        return {}

    section_year_ids = {row.id_section_year for row in cursadas}
    totals = await session_counts(
        db, section_year_ids, from_date=from_date, to_date=to_date
    )
    attended = await attended_counts(
        db,
        [row.id_student_section_year for row in cursadas],
        from_date=from_date,
        to_date=to_date,
    )
    return {
        row.id_student_section_year: _to_public(
            attended.get(row.id_student_section_year, 0),
            totals.get(row.id_section_year, 0),
        )
        for row in cursadas
    }
