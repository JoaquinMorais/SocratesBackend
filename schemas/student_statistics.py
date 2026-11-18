from typing import Literal

from sqlmodel import SQLModel

from schemas.attendance import AttendanceStatsPublic
from schemas.status import StatusPublic
from schemas.student_evaluation import StudentEvaluationGradeSummaryPublic

StudentStatisticsPopulation = Literal["registered", "attending"]


class StudentMembershipStatsPublic(SQLModel):
    active: int = 0
    finished: int = 0
    pending_approval: int = 0
    abandoned: int = 0
    expelled: int = 0
    rejected: int = 0


class StudentStatisticsAttendancePublic(SQLModel):
    members_with_attendance: int = 0
    attended_classes: int = 0
    total_classes: int = 0
    attendance_percentage: float | None = None


class StudentStatisticsSummaryPublic(SQLModel):
    students_total: int
    section_years_total: int
    with_project: int
    without_project: int
    memberships_by_status: StudentMembershipStatsPublic
    attendance: StudentStatisticsAttendancePublic


class StudentStatisticsSectionYearPublic(SQLModel):
    id_section_year: int
    year: int
    id_section: int
    section_name: str
    students_total: int
    with_project: int
    without_project: int
    memberships_by_status: StudentMembershipStatsPublic
    attendance: StudentStatisticsAttendancePublic


class StudentStatisticsMembershipPublic(SQLModel):
    id_project: int
    id_section_year: int
    group_number: int
    project_name: str | None = None
    status: StatusPublic


class StudentStatisticsSectionYearRowPublic(SQLModel):
    id_section_year: int
    year: int
    id_section: int
    section_name: str
    state: str
    status: StatusPublic
    attendance: AttendanceStatsPublic | None = None
    student_evaluations: list[StudentEvaluationGradeSummaryPublic] = []
    average_student_evaluation: float | None = None


class StudentStatisticsItemPublic(SQLModel):
    id_student: int
    first_name: str
    last_name: str
    legajo: int
    section_years: list[StudentStatisticsSectionYearRowPublic]
    project_memberships: list[StudentStatisticsMembershipPublic]
    with_project: bool


class StudentStatisticsPublic(SQLModel):
    population: StudentStatisticsPopulation
    statistics: StudentStatisticsSummaryPublic
    by_section_year: list[StudentStatisticsSectionYearPublic]
    items: list[StudentStatisticsItemPublic]
    total: int
    limit: int
    offset: int
