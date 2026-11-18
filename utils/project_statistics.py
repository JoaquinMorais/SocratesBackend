from sqlalchemy import func
from sqlmodel import select

from models import (
    DeliveryComment,
    ProjectTechnology,
    Status,
    StudentProject,
    Technology,
)
from schemas.project_statistics import (
    ActivityStatisticsPublic,
    AttendanceStatisticsPublic,
    CommentStatisticsPublic,
    DeliveryStatusCountsPublic,
    MemberStatusCountsPublic,
    ProjectStatisticsPublic,
    ProjectStatisticsSummaryPublic,
    ProjectTechnologyStatisticsPublic,
)
from utils.project_evaluations import build_project_evaluation


def _average(values: list[int]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


async def build_project_statistics(db, project) -> ProjectStatisticsPublic:
    evaluation = await build_project_evaluation(db, project)
    deliveries = evaluation.activities

    delivery_counts = {
        "requested": 0,
        "pending_approval": 0,
        "pending_modification": 0,
        "approved": 0,
    }
    activity_statistics = []
    for delivery in deliveries:
        delivery_counts[delivery.status.code] = (
            delivery_counts.get(delivery.status.code, 0) + 1
        )
        latest = {
            grade.category: grade for grade in delivery.latest_grades
        }
        latest_values = [grade.score.value for grade in delivery.latest_grades]
        all_values = [grade.score.value for grade in delivery.grades]
        activity_statistics.append(
            ActivityStatisticsPublic(
                id_activity=delivery.activity.id_activity,
                id_delivery=delivery.id_delivery,
                title=delivery.activity.title,
                due_date=delivery.activity.due_date,
                delivery_status=delivery.status,
                grades_total=len(delivery.grades),
                latest_activity=latest.get("activity"),
                latest_follow_up=latest.get("follow_up"),
                average_latest=_average(latest_values),
                average_all=_average(all_values),
            )
        )

    member_rows = (
        await db.exec(
            select(Status.code, func.count())
            .select_from(StudentProject)
            .join(Status, Status.id_status == StudentProject.id_status)
            .where(
                StudentProject.id_project == project.id_project,
                Status.ambito == "student_project",
            )
            .group_by(Status.code)
        )
    ).all()
    member_counts = MemberStatusCountsPublic(
        **{code: count for code, count in member_rows}
    )

    delivery_ids = [delivery.id_delivery for delivery in deliveries]
    comment_rows = (
        (
            await db.exec(
                select(DeliveryComment.kind, Status.code, func.count())
                .join(Status, Status.id_status == DeliveryComment.id_status)
                .where(DeliveryComment.id_delivery.in_(delivery_ids))
                .group_by(DeliveryComment.kind, Status.code)
            )
        ).all()
        if delivery_ids
        else []
    )
    comments = CommentStatisticsPublic()
    for kind, code, count in comment_rows:
        if kind == "annotation":
            comments.annotations_total += count
        elif code == "requested":
            comments.feedback_requested += count
        elif code == "corrected":
            comments.feedback_corrected += count
    comments.feedback_total = (
        comments.feedback_requested + comments.feedback_corrected
    )

    technology_rows = (
        await db.exec(
            select(Technology.id_technology, Technology.name)
            .join(
                ProjectTechnology,
                ProjectTechnology.id_technology == Technology.id_technology,
            )
            .where(ProjectTechnology.id_project == project.id_project)
            .order_by(Technology.name, Technology.id_technology)
        )
    ).all()
    technologies = [
        ProjectTechnologyStatisticsPublic(
            id_technology=id_technology, name=name
        )
        for id_technology, name in technology_rows
    ]

    evaluation_stats = evaluation.statistics
    statistics = ProjectStatisticsSummaryPublic(
        activities_total=len(deliveries),
        deliveries_by_status=DeliveryStatusCountsPublic(**delivery_counts),
        members_by_status=member_counts,
        members_total=(
            member_counts.active
            + member_counts.finished
            + member_counts.pending_approval
            + member_counts.abandoned
            + member_counts.expelled
            + member_counts.rejected
        ),
        grades_total=evaluation_stats.grades_total,
        latest_grades_total=evaluation_stats.latest_grades_total,
        average_latest=evaluation_stats.average_latest,
        average_all=evaluation_stats.average_all,
        average_latest_activity=evaluation_stats.average_latest_activity,
        average_latest_follow_up=evaluation_stats.average_latest_follow_up,
        attendance=AttendanceStatisticsPublic(
            members_with_attendance=sum(
                1
                for member in evaluation.members
                if member.attendance is not None
                and member.attendance.total_classes > 0
            ),
            attended_classes=evaluation_stats.attendance.attended_classes,
            total_classes=evaluation_stats.attendance.total_classes,
            attendance_percentage=(
                evaluation_stats.attendance.attendance_percentage
            ),
        ),
        comments=comments,
        technologies_total=len(technologies),
        student_evaluations=evaluation_stats.student_evaluations,
    )

    return ProjectStatisticsPublic(
        project=evaluation.project,
        statistics=statistics,
        activity_statistics=activity_statistics,
        member_statistics=evaluation.members,
        technologies=technologies,
    )
