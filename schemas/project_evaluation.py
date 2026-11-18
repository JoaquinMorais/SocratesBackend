from sqlmodel import SQLModel

from schemas.attendance import AttendanceStatsPublic
from schemas.delivery import DeliveryPublic
from schemas.project import ProjectPublic
from schemas.section_year import SectionYearPublic
from schemas.student_evaluation import (
    StudentEvaluationMemberPublic,
    StudentEvaluationSummaryPublic,
)


class ProjectEvaluationStatsPublic(SQLModel):
    deliveries_total: int
    deliveries_with_link: int
    graded_deliveries: int
    grades_total: int
    latest_grades_total: int
    average_latest: float | None = None
    average_all: float | None = None
    average_latest_activity: float | None = None
    average_latest_follow_up: float | None = None
    attendance: AttendanceStatsPublic
    members_total: int
    members_active: int
    members_finished: int
    student_evaluations: StudentEvaluationSummaryPublic


class ProjectEvaluationPublic(SQLModel):
    project: ProjectPublic
    activities: list[DeliveryPublic]
    statistics: ProjectEvaluationStatsPublic
    members: list[StudentEvaluationMemberPublic]


class SectionYearEvaluationsPublic(SQLModel):
    section_year: SectionYearPublic
    projects: list[ProjectEvaluationPublic]
