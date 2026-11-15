from collections import defaultdict

from fastapi import HTTPException, status
from sqlalchemy import false
from sqlmodel import col, select

from models import (
    Project,
    Section,
    SectionYear,
    Status,
    Student,
    StudentProject,
    StudentSectionYear,
    User,
)
from models.state.student_section_year import ATTENDING, REGISTERED
from schemas.student_statistics import (
    StudentMembershipStatsPublic,
    StudentStatisticsAttendancePublic,
    StudentStatisticsItemPublic,
    StudentStatisticsMembershipPublic,
    StudentStatisticsPublic,
    StudentStatisticsSectionYearPublic,
    StudentStatisticsSectionYearRowPublic,
    StudentStatisticsSummaryPublic,
)
from utils.attendance_stats import attendance_stats_for_cursadas
from utils.section_years import get_section_year
from utils.statuses import to_public as status_public

MEMBER_STATUSES = frozenset({"active", "finished"})
MEMBERSHIP_STATUSES = (
    "active",
    "finished",
    "pending_approval",
    "abandoned",
    "expelled",
    "rejected",
)


def _forbidden() -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Only a professor of this section year or a super admin can see statistics",
    )


def _membership_counts(memberships) -> StudentMembershipStatsPublic:
    counts = StudentMembershipStatsPublic()
    for membership in memberships:
        code = membership.status.code
        if code in MEMBERSHIP_STATUSES:
            setattr(counts, code, getattr(counts, code) + 1)
    return counts


def _attendance_stats(rows, stats_by_row) -> StudentStatisticsAttendancePublic:
    attended = 0
    total = 0
    student_ids = set()
    for row in rows:
        stat = stats_by_row.get(row.id_student_section_year)
        if stat is None:
            continue
        attended += stat.attended_classes
        total += stat.total_classes
        if stat.total_classes > 0:
            student_ids.add(row.id_student)
    return StudentStatisticsAttendancePublic(
        members_with_attendance=len(student_ids),
        attended_classes=attended,
        total_classes=total,
        attendance_percentage=(
            round(attended * 100 / total, 2) if total else None
        ),
    )


async def build_student_statistics(
    db,
    access,
    *,
    population: str,
    id_section_year: int | None,
    year: int | None,
    id_section: int | None,
    limit: int,
    offset: int,
) -> StudentStatisticsPublic:
    if id_section_year is not None:
        await get_section_year(db, id_section_year)
        if not access.can_manage(id_section_year):
            raise _forbidden()

    scope = [SectionYear.is_generic == False]  # noqa: E712
    if id_section_year is not None:
        scope.append(SectionYear.id_section_year == id_section_year)
    if year is not None:
        scope.append(SectionYear.year == year)
    if id_section is not None:
        scope.append(SectionYear.id_section == id_section)
    if not access.is_super_admin:
        if access.section_year_ids:
            scope.append(
                SectionYear.id_section_year.in_(access.section_year_ids)
            )
        else:
            scope.append(false())

    target_state = REGISTERED if population == "registered" else ATTENDING
    rows = (
        await db.exec(
            select(StudentSectionYear, Student, User, SectionYear, Section, Status)
            .join(Student, Student.id_student == StudentSectionYear.id_student)
            .join(User, User.id_user == Student.id_student)
            .join(
                SectionYear,
                SectionYear.id_section_year
                == StudentSectionYear.id_section_year,
            )
            .join(Section, Section.id_section == SectionYear.id_section)
            .join(Status, Status.id_status == StudentSectionYear.id_status)
            .where(StudentSectionYear.state == target_state, *scope)
            .order_by(
                col(User.last_name),
                col(User.first_name),
                col(Student.id_student),
            )
        )
    ).all()

    rows_by_student: dict[int, list] = defaultdict(list)
    students: dict[int, tuple[Student, User]] = {}
    section_years: dict[int, SectionYear] = {}
    section_names: dict[int, str] = {}
    rows_by_section_year: dict[int, list] = defaultdict(list)
    for row, student, user, section_year, section, row_status in rows:
        rows_by_student[student.id_student].append(
            (row, section_year, section, row_status)
        )
        students[student.id_student] = (student, user)
        section_years[section_year.id_section_year] = section_year
        section_names[section_year.id_section_year] = section.name
        rows_by_section_year[section_year.id_section_year].append(row)

    student_ids = list(rows_by_student)
    section_year_ids = list(section_years)
    memberships_by_student: dict[int, list] = defaultdict(list)
    if student_ids and section_year_ids:
        membership_rows = (
            await db.exec(
                select(StudentProject, Project, Status)
                .join(Project, Project.id_project == StudentProject.id_project)
                .join(Status, Status.id_status == StudentProject.id_status)
                .where(
                    StudentProject.id_student.in_(student_ids),
                    Project.id_section_year.in_(section_year_ids),
                    Status.ambito == "student_project",
                )
                .order_by(
                    Project.id_section_year.desc(),
                    Project.group_number,
                    StudentProject.id_student_project,
                )
            )
        ).all()
        for membership, project, membership_status in membership_rows:
            memberships_by_student[membership.id_student].append(
                (membership, project, membership_status)
            )

    stats_by_row = {}
    if target_state == ATTENDING:
        cursadas = [row for row, *_ in rows]
        stats_by_row = await attendance_stats_for_cursadas(db, cursadas)

    def memberships_for(
        ids: set[int] | list[int], id_section_year_value: int | None = None
    ):
        return [
            (membership, project, membership_status)
            for id_student in ids
            for membership, project, membership_status in memberships_by_student.get(
                id_student, []
            )
            if (
                id_section_year_value is None
                or project.id_section_year == id_section_year_value
            )
        ]

    def with_project_count(
        ids: set[int] | list[int], id_section_year_value: int | None = None
    ) -> int:
        return sum(
            1
            for id_student in ids
            if any(
                membership.status.code in MEMBER_STATUSES
                and (
                    id_section_year_value is None
                    or project.id_section_year == id_section_year_value
                )
                for membership, project, *_ in memberships_by_student.get(
                    id_student, []
                )
            )
        )

    all_students = set(student_ids)
    all_memberships = memberships_for(all_students)
    global_attendance = _attendance_stats(
        [row for row, *_ in rows], stats_by_row
    )
    with_project = with_project_count(all_students)

    by_section_year = []
    for sy_id, sy in sorted(
        section_years.items(),
        key=lambda item: (-item[1].year, section_names[item[0]]),
    ):
        sy_students = {
            row.id_student for row in rows_by_section_year[sy_id]
        }
        sy_memberships = memberships_for(sy_students, sy_id)
        sy_with_project = with_project_count(sy_students, sy_id)
        by_section_year.append(
            StudentStatisticsSectionYearPublic(
                id_section_year=sy.id_section_year,
                year=sy.year,
                id_section=sy.id_section,
                section_name=section_names[sy_id],
                students_total=len(sy_students),
                with_project=sy_with_project,
                without_project=len(sy_students) - sy_with_project,
                memberships_by_status=_membership_counts(
                    [membership for membership, *_ in sy_memberships]
                ),
                attendance=_attendance_stats(
                    rows_by_section_year[sy_id], stats_by_row
                ),
            )
        )

    ordered_ids = sorted(
        student_ids,
        key=lambda id_student: (
            students[id_student][1].last_name,
            students[id_student][1].first_name,
            id_student,
        ),
    )
    page_ids = ordered_ids[offset : offset + limit]
    items = []
    for id_student in page_ids:
        student, user = students[id_student]
        student_rows = sorted(
            rows_by_student[id_student],
            key=lambda item: (-item[1].year, item[2].name),
        )
        memberships = memberships_by_student.get(id_student, [])
        items.append(
            StudentStatisticsItemPublic(
                id_student=id_student,
                first_name=user.first_name,
                last_name=user.last_name,
                legajo=user.legajo,
                section_years=[
                    StudentStatisticsSectionYearRowPublic(
                        id_section_year=section_year.id_section_year,
                        year=section_year.year,
                        id_section=section.id_section,
                        section_name=section.name,
                        state=row.state,
                        status=status_public(row_status),
                        attendance=stats_by_row.get(row.id_student_section_year),
                    )
                    for row, section_year, section, row_status in student_rows
                ],
                project_memberships=[
                    StudentStatisticsMembershipPublic(
                        id_project=project.id_project,
                        id_section_year=project.id_section_year,
                        group_number=project.group_number,
                        project_name=project.name,
                        status=status_public(membership_status),
                    )
                    for _, project, membership_status in memberships
                ],
                with_project=any(
                    membership.status.code in MEMBER_STATUSES
                    for membership, *_ in memberships
                ),
            )
        )

    return StudentStatisticsPublic(
        population=population,
        statistics=StudentStatisticsSummaryPublic(
            students_total=len(all_students),
            section_years_total=len(section_years),
            with_project=with_project,
            without_project=len(all_students) - with_project,
            memberships_by_status=_membership_counts(
                [membership for membership, *_ in all_memberships]
            ),
            attendance=global_attendance,
        ),
        by_section_year=by_section_year,
        items=items,
        total=len(all_students),
        limit=limit,
        offset=offset,
    )
