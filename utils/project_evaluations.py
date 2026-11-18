from sqlmodel import select

from models import Activity, Delivery, DeliveryGrade, Project, StudentSectionYear
from models.state import MEMBER_CODES
from schemas.student_evaluation import StudentEvaluationMemberPublic
from schemas.attendance import AttendanceStatsPublic
from schemas.project_evaluation import (
    ProjectEvaluationPublic,
    ProjectEvaluationStatsPublic,
    SectionYearEvaluationsPublic,
)
from utils.deliveries import to_public as delivery_public
from utils.project_attendance import list_project_attendance
from utils.projects import to_public as project_public
from utils.section_years import to_public as section_year_public
from utils.student_evaluations import (
    evaluation_average,
    evaluation_summary,
    grades_for_cursadas,
)


def _average(values: list[int]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


async def build_project_evaluation(db, project) -> ProjectEvaluationPublic:
    """Arma actividades, notas, asistencia y estadísticas de un proyecto."""
    deliveries = (
        await db.exec(
            select(Delivery)
            .join(Activity, Activity.id_activity == Delivery.id_activity)
            .where(Delivery.id_project == project.id_project)
            .order_by(
                Activity.due_date,
                Activity.due_time,
                Delivery.id_activity,
            )
        )
    ).all()
    delivery_ids = [delivery.id_delivery for delivery in deliveries]
    grade_rows = (
        (
            await db.exec(
                select(DeliveryGrade)
                .where(DeliveryGrade.id_delivery.in_(delivery_ids))
                .order_by(
                    DeliveryGrade.graded_at.desc(),
                    DeliveryGrade.id_delivery_grade.desc(),
                )
            )
        ).all()
        if delivery_ids
        else []
    )
    grades_by_delivery: dict[int, list[DeliveryGrade]] = {}
    for grade in grade_rows:
        grades_by_delivery.setdefault(grade.id_delivery, []).append(grade)
    activities = [
        delivery_public(delivery, grades_by_delivery.get(delivery.id_delivery, []))
        for delivery in deliveries
    ]

    latest_grades = [
        grade
        for activity in activities
        for grade in activity.latest_grades
    ]
    all_values = [grade.score.value for grade in grade_rows]
    latest_values = [grade.score.value for grade in latest_grades]
    latest_activity_values = [
        grade.score.value
        for grade in latest_grades
        if grade.category == "activity"
    ]
    latest_follow_up_values = [
        grade.score.value
        for grade in latest_grades
        if grade.category == "follow_up"
    ]

    attendance = await list_project_attendance(
        db,
        project,
        statuses=list(MEMBER_CODES),
        from_date=None,
        to_date=None,
        limit=100,
        offset=0,
    )
    member_ids = [item.id_student for item in attendance.items]
    cursadas = (
        (
            await db.exec(
                select(StudentSectionYear).where(
                    StudentSectionYear.id_section_year == project.id_section_year,
                    StudentSectionYear.id_student.in_(member_ids),
                    StudentSectionYear.state != "registered",
                )
            )
        ).all()
        if member_ids
        else []
    )
    cursada_by_student = {row.id_student: row for row in cursadas}
    student_grades = await grades_for_cursadas(
        db, [row.id_student_section_year for row in cursadas]
    )
    members = [
        StudentEvaluationMemberPublic(
            **item.model_dump(),
            student_evaluations=student_grades.get(
                cursada_by_student[item.id_student].id_student_section_year, []
            )
            if item.id_student in cursada_by_student
            else [],
            average_student_evaluation=(
                evaluation_average(
                    student_grades.get(
                        cursada_by_student[item.id_student].id_student_section_year,
                        [],
                    )
                )
                if item.id_student in cursada_by_student
                else None
            ),
        )
        for item in attendance.items
    ]
    student_evaluation_summary = evaluation_summary(student_grades)

    attended = sum(
        item.attendance.attended_classes
        for item in attendance.items
        if item.attendance is not None
    )
    total_classes = sum(
        item.attendance.total_classes
        for item in attendance.items
        if item.attendance is not None
    )
    attendance_percentage = (
        round(attended * 100 / total_classes, 2) if total_classes else None
    )

    statistics = ProjectEvaluationStatsPublic(
        deliveries_total=len(activities),
        deliveries_with_link=sum(1 for item in activities if item.link is not None),
        graded_deliveries=len({grade.id_delivery for grade in grade_rows}),
        grades_total=len(grade_rows),
        latest_grades_total=len(latest_grades),
        average_latest=_average(latest_values),
        average_all=_average(all_values),
        average_latest_activity=_average(latest_activity_values),
        average_latest_follow_up=_average(latest_follow_up_values),
        attendance=AttendanceStatsPublic(
            attended_classes=attended,
            total_classes=total_classes,
            attendance_percentage=attendance_percentage,
        ),
        members_total=len(attendance.items),
        members_active=sum(
            1 for item in attendance.items if item.status.code == "active"
        ),
        members_finished=sum(
            1 for item in attendance.items if item.status.code == "finished"
        ),
        student_evaluations=student_evaluation_summary,
    )

    return ProjectEvaluationPublic(
        project=project_public(project),
        activities=activities,
        statistics=statistics,
        members=members,
    )


async def build_section_year_evaluations(
    db, section_year
) -> SectionYearEvaluationsPublic:
    """Evaluaciones de todos los proyectos de un curso lectivo."""
    projects = (
        await db.exec(
            select(Project)
            .where(Project.id_section_year == section_year.id_section_year)
            .order_by(Project.group_number, Project.id_project)
        )
    ).all()
    return SectionYearEvaluationsPublic(
        section_year=section_year_public(section_year),
        projects=[
            await build_project_evaluation(db, project) for project in projects
        ],
    )
