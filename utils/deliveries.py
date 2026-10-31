from datetime import datetime, time, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from models import Activity, Calendar, Delivery, Project
from schemas.activity import ActivityPublic
from schemas.delivery import (
    DeliveryList,
    DeliveryProjectSummary,
    DeliveryPublic,
    DeliveryRepairCreate,
    DeliveryUpdate,
)


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Delivery not found")


def _project_not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")


def _activity_not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Activity not found")


def _duplicate() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT, "This project already has a delivery for that activity"
    )


def _mismatch() -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Activity does not belong to the project's section year",
    )


def _forbidden() -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Only a project member, its professor or a super admin can do this",
    )


def _grades_forbidden() -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Only a professor of this section year or a super admin can grade deliveries",
    )


def _final_for_student() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        "A student cannot modify deliveries of a final project",
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def ensure_deliveries_for_section_year(db, id_section_year: int) -> None:
    """Pre-crea las entregas de todas las combinaciones proyecto × actividad."""
    statement = (
        insert(Delivery)
        .from_select(
            ["id_project", "id_activity"],
            select(Project.id_project, Activity.id_activity)
            .select_from(Project)
            .join(Calendar, Calendar.id_section_year == Project.id_section_year)
            .join(Activity, Activity.id_calendar == Calendar.id_calendar)
            .where(Project.id_section_year == id_section_year),
        )
        .on_conflict_do_nothing(index_elements=["id_project", "id_activity"])
    )
    await db.exec(statement)


async def get_delivery(db, id_delivery: int) -> Delivery:
    delivery = await db.get(Delivery, id_delivery)
    if not delivery:
        raise _not_found()
    return delivery


async def _get_project(db, id_project: int) -> Project:
    project = await db.get(Project, id_project)
    if not project:
        raise _project_not_found()
    return project


async def _get_activity(db, id_activity: int) -> Activity:
    activity = await db.get(Activity, id_activity)
    if not activity:
        raise _activity_not_found()
    return activity


def _can_read(access, project: Project) -> bool:
    return access.can_manage(project.id_section_year) or (
        project.id_project in access.project_ids
    )


def _is_staff(access, project: Project) -> bool:
    return access.can_manage(project.id_section_year)


def _can_edit(access, project: Project) -> bool:
    return _is_staff(access, project) or project.id_project in access.project_ids


def _activity_public(activity: Activity) -> ActivityPublic:
    return ActivityPublic(
        id_activity=activity.id_activity,
        id_calendar=activity.id_calendar,
        id_section_year=activity.calendar.id_section_year,
        title=activity.title,
        description=activity.description,
        due_date=activity.due_date,
        due_time=activity.due_time,
    )


def to_public(delivery: Delivery) -> DeliveryPublic:
    project = delivery.project
    return DeliveryPublic(
        id_delivery=delivery.id_delivery,
        id_project=delivery.id_project,
        id_activity=delivery.id_activity,
        id_section_year=delivery.activity.calendar.id_section_year,
        activity=_activity_public(delivery.activity),
        project=DeliveryProjectSummary(
            id_project=project.id_project,
            group_number=project.group_number,
            name=project.name,
        ),
        link=delivery.link,
        activity_grade=delivery.activity_grade,
        development_grade=delivery.development_grade,
        submitted_at=delivery.submitted_at,
        updated_at=delivery.updated_at,
    )


async def list_project_deliveries(
    db,
    access,
    id_project: int,
    *,
    limit: int,
    offset: int,
) -> DeliveryList:
    project = await _get_project(db, id_project)
    if not _can_read(access, project):
        raise _forbidden()

    conditions = [Delivery.id_project == id_project]
    total = (
        await db.exec(
            select(func.count()).select_from(Delivery).where(*conditions)
        )
    ).scalar_one()
    items = (
        await db.exec(
            select(Delivery)
            .where(*conditions)
            .order_by(Delivery.id_activity, Delivery.id_delivery)
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    items = sorted(
        items,
        key=lambda item: (
            item.activity.due_date,
            item.activity.due_time or time.min,
            item.id_activity,
        ),
    )
    return DeliveryList(
        items=[to_public(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


async def list_activity_deliveries(
    db,
    access,
    id_activity: int,
    *,
    limit: int,
    offset: int,
) -> DeliveryList:
    activity = await _get_activity(db, id_activity)
    if not access.can_manage(activity.calendar.id_section_year):
        raise _forbidden()

    conditions = [Delivery.id_activity == id_activity]
    total = (
        await db.exec(
            select(func.count()).select_from(Delivery).where(*conditions)
        )
    ).scalar_one()
    items = (
        await db.exec(
            select(Delivery)
            .where(*conditions)
            .order_by(Delivery.id_project, Delivery.id_delivery)
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    items = sorted(
        items,
        key=lambda item: (item.project.group_number, item.id_project),
    )
    return DeliveryList(
        items=[to_public(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


def _validate_update_permissions(
    access, project: Project, data: DeliveryUpdate | DeliveryRepairCreate
) -> bool:
    staff = _is_staff(access, project)
    if not _can_edit(access, project):
        raise _forbidden()
    if staff:
        return True

    fields = data.model_fields_set
    if "activity_grade" in fields or "development_grade" in fields:
        raise _grades_forbidden()
    if project.status.is_final:
        raise _final_for_student()
    return False


def _apply_values(
    delivery: Delivery,
    data: DeliveryUpdate | DeliveryRepairCreate,
) -> None:
    fields = data.model_fields_set
    now = _now()
    if "link" in fields:
        delivery.link = data.link
        if data.link is None:
            delivery.submitted_at = None
        elif delivery.submitted_at is None:
            delivery.submitted_at = now
    if "activity_grade" in fields:
        delivery.activity_grade = data.activity_grade
    if "development_grade" in fields:
        delivery.development_grade = data.development_grade
    delivery.updated_at = now


async def update_delivery(
    db, access, id_delivery: int, data: DeliveryUpdate
) -> DeliveryPublic:
    delivery = await get_delivery(db, id_delivery)
    project = delivery.project
    if not data.model_fields_set:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No fields to update")
    _validate_update_permissions(access, project, data)

    _apply_values(delivery, data)
    db.add(delivery)
    await db.commit()
    return to_public(delivery)


async def create_delivery(
    db, access, id_project: int, data: DeliveryRepairCreate
) -> DeliveryPublic:
    project = await _get_project(db, id_project)
    _validate_update_permissions(access, project, data)
    activity = await _get_activity(db, data.id_activity)
    if activity.calendar.id_section_year != project.id_section_year:
        raise _mismatch()

    existing = (
        await db.exec(
            select(Delivery.id_delivery).where(
                Delivery.id_project == id_project,
                Delivery.id_activity == data.id_activity,
            )
        )
    ).first()
    if existing is not None:
        raise _duplicate()

    delivery = Delivery(
        id_project=id_project,
        id_activity=data.id_activity,
        project=project,
        activity=activity,
    )
    _apply_values(delivery, data)
    db.add(delivery)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise _duplicate()
    return to_public(delivery)


async def has_delivery_data_for_activity(db, id_activity: int) -> bool:
    found = (
        await db.exec(
            select(Delivery.id_delivery)
            .where(
                Delivery.id_activity == id_activity,
                _has_data_condition(),
            )
            .limit(1)
        )
    ).first()
    return found is not None


async def has_delivery_data_for_project(db, id_project: int) -> bool:
    found = (
        await db.exec(
            select(Delivery.id_delivery)
            .where(
                Delivery.id_project == id_project,
                _has_data_condition(),
            )
            .limit(1)
        )
    ).first()
    return found is not None


async def has_delivery_data_for_section_year(db, id_section_year: int) -> bool:
    found = (
        await db.exec(
            select(Delivery.id_delivery)
            .join(Activity, Activity.id_activity == Delivery.id_activity)
            .join(Calendar, Calendar.id_calendar == Activity.id_calendar)
            .where(
                Calendar.id_section_year == id_section_year,
                _has_data_condition(),
            )
            .limit(1)
        )
    ).first()
    return found is not None


def _has_data_condition():
    return or_(
        Delivery.link.is_not(None),
        Delivery.activity_grade.is_not(None),
        Delivery.development_grade.is_not(None),
    )
