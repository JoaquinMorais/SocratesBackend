from datetime import date

from sqlmodel import SQLModel

from schemas.delivery import DeliveryGradePublic
from schemas.project import ProjectPublic
from schemas.status import StatusPublic
from schemas.student_evaluation import (
    StudentEvaluationMemberPublic,
    StudentEvaluationSummaryPublic,
)


class DeliveryStatusCountsPublic(SQLModel):
    requested: int = 0
    pending_approval: int = 0
    pending_modification: int = 0
    approved: int = 0


class MemberStatusCountsPublic(SQLModel):
    active: int = 0
    finished: int = 0
    pending_approval: int = 0
    abandoned: int = 0
    expelled: int = 0
    rejected: int = 0


class CommentStatisticsPublic(SQLModel):
    feedback_total: int = 0
    feedback_requested: int = 0
    feedback_corrected: int = 0
    annotations_total: int = 0


class AttendanceStatisticsPublic(SQLModel):
    members_with_attendance: int = 0
    attended_classes: int = 0
    total_classes: int = 0
    attendance_percentage: float | None = None


class ProjectStatisticsSummaryPublic(SQLModel):
    activities_total: int
    deliveries_by_status: DeliveryStatusCountsPublic
    members_by_status: MemberStatusCountsPublic
    members_total: int
    grades_total: int
    latest_grades_total: int
    average_latest: float | None = None
    average_all: float | None = None
    average_latest_activity: float | None = None
    average_latest_follow_up: float | None = None
    attendance: AttendanceStatisticsPublic
    comments: CommentStatisticsPublic
    technologies_total: int
    student_evaluations: StudentEvaluationSummaryPublic


class ActivityStatisticsPublic(SQLModel):
    id_activity: int
    id_delivery: int
    title: str
    due_date: date
    delivery_status: StatusPublic
    grades_total: int
    latest_activity: DeliveryGradePublic | None = None
    latest_follow_up: DeliveryGradePublic | None = None
    average_latest: float | None = None
    average_all: float | None = None


class ProjectTechnologyStatisticsPublic(SQLModel):
    id_technology: int
    name: str


class ProjectStatisticsPublic(SQLModel):
    project: ProjectPublic
    statistics: ProjectStatisticsSummaryPublic
    activity_statistics: list[ActivityStatisticsPublic]
    member_statistics: list[StudentEvaluationMemberPublic]
    technologies: list[ProjectTechnologyStatisticsPublic]
