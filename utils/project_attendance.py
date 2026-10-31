from datetime import date

from sqlmodel import select

from models import StudentSectionYear
from models.student_section_year import REGISTERED
from schemas.student_project import (
    StudentProjectAttendanceList,
    StudentProjectAttendancePublic,
)
from utils.attendance_stats import attendance_stats_for_cursadas
from utils.student_projects import list_members


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
    section = project.section_year.section
    return StudentProjectAttendanceList(
        id_project=project.id_project,
        id_section_year=project.id_section_year,
        year=project.section_year.year,
        id_section=section.id_section,
        section_name=section.name,
        group_number=project.group_number,
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )
