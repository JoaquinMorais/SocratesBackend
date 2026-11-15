from datetime import date

from sqlmodel import select

from models import StudentSectionYear
from models.state.student_section_year import REGISTERED
from schemas.student_project import (
    StudentProjectAttendanceList,
    StudentProjectAttendancePublic,
    StudentProjectAttendanceStatsPublic,
)
from utils.attendance_stats import attendance_stats_for_cursadas
from utils.student_projects import list_all_members, list_members


async def list_project_attendance(
    db,
    project,
    *,
    statuses: list[str],
    from_date: date | None,
    to_date: date | None,
    limit: int,
    offset: int,
) -> StudentProjectAttendanceList:
    """Integrantes de un proyecto con su asistencia en el curso lectivo."""
    members, total = await list_members(
        db,
        project.id_project,
        statuses=statuses,
        limit=limit,
        offset=offset,
    )
    member_ids = [member.id_student for member in members]
    cursadas = (
        (
            await db.exec(
                select(StudentSectionYear).where(
                    StudentSectionYear.id_section_year == project.id_section_year,
                    StudentSectionYear.id_student.in_(member_ids),
                    StudentSectionYear.state != REGISTERED,
                )
            )
        ).all()
        if member_ids
        else []
    )
    cursada_by_student = {row.id_student: row for row in cursadas}
    stats = await attendance_stats_for_cursadas(
        db, cursadas, from_date=from_date, to_date=to_date
    )

    items = [
        StudentProjectAttendancePublic(
            **member.model_dump(),
            attendance=(
                stats.get(
                    cursada_by_student[member.id_student].id_student_section_year
                )
                if member.id_student in cursada_by_student
                else None
            ),
        )
        for member in members
    ]

    all_members = await list_all_members(
        db, project.id_project, statuses=statuses
    )
    all_ids = [member.id_student for member in all_members]
    all_cursadas = (
        (
            await db.exec(
                select(StudentSectionYear).where(
                    StudentSectionYear.id_section_year == project.id_section_year,
                    StudentSectionYear.id_student.in_(all_ids),
                    StudentSectionYear.state != REGISTERED,
                )
            )
        ).all()
        if all_ids
        else []
    )
    all_stats = await attendance_stats_for_cursadas(
        db, all_cursadas, from_date=from_date, to_date=to_date
    )
    attended_total = sum(
        stat.attended_classes
        for stat in all_stats.values()
    )
    classes_total = sum(
        stat.total_classes
        for stat in all_stats.values()
    )
    statistics = StudentProjectAttendanceStatsPublic(
        members_total=len(all_members),
        members_with_attendance=sum(
            1
            for cursada in all_cursadas
            if (
                all_stats.get(cursada.id_student_section_year) is not None
                and all_stats[cursada.id_student_section_year].total_classes > 0
            )
        ),
        attended_classes=attended_total,
        total_classes=classes_total,
        attendance_percentage=(
            round(attended_total * 100 / classes_total, 2)
            if classes_total
            else None
        ),
    )
    section = project.section_year.section
    return StudentProjectAttendanceList(
        id_project=project.id_project,
        id_section_year=project.id_section_year,
        year=project.section_year.year,
        id_section=section.id_section,
        section_name=section.name,
        group_number=project.group_number,
        statistics=statistics,
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )
