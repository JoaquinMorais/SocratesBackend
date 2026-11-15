from sqlmodel import SQLModel

from schemas.attendance import AttendanceStatsPublic
from schemas.delivery import DeliveryPublic
from schemas.project import ProjectPublic
from schemas.section_year import SectionYearPublic
from schemas.student_project import StudentProjectAttendancePublic


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


class ProjectEvaluationPublic(SQLModel):
    project: ProjectPublic
    activities: list[DeliveryPublic]
    statistics: ProjectEvaluationStatsPublic
    members: list[StudentProjectAttendancePublic]


class SectionYearEvaluationsPublic(SQLModel):
    section_year: SectionYearPublic
    projects: list[ProjectEvaluationPublic]
