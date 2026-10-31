from datetime import date

from fastapi import HTTPException, status
from sqlmodel import col, func, select

from models import Activity, Calendar
from schemas.activity import (
    ActivityCreate,
    ActivityPublic,
    ActivityUpdate,
)
from utils.date_ranges import validate_optional_range
from utils.deliveries import (
    ensure_deliveries_for_section_year,
    has_delivery_data_for_activity,
)
from utils.section_years import (
    ensure_calendar,
    get_section_year,
    require_view_section_year,
)


def to_public(activity: Activity, calendar: Calendar | None = None) -> ActivityPublic:
    calendar = calendar or activity.calendar
    return ActivityPublic(
        id_activity=activity.id_activity,
        id_calendar=activity.id_calendar,
        id_section_year=calendar.id_section_year,
        title=activity.title,
        description=activity.description,
        due_date=activity.due_date,
        due_time=activity.due_time,
    )


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Activity not found")


def _forbidden() -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Only a professor of this section year or a super admin can do this",
    )


def _outside_year() -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Activity dates must be in the section year",
    )


async def get_activity(db, id_activity: int) -> Activity:
    activity = await db.get(Activity, id_activity)
    if not activity:
        raise _not_found()
    return activity


def _check_year(calendar: Calendar, due_date: date) -> None:
    if due_date.year != calendar.section_year.year:
        raise _outside_year()


async def create_activity(
    db, access, id_section_year: int, data: ActivityCreate
) -> ActivityPublic:
    await get_section_year(db, id_section_year)
    if not access.can_manage(id_section_year):
        raise _forbidden()
    calendar = await ensure_calendar(db, id_section_year)
    _check_year(calendar, data.due_date)

    activity = Activity(id_calendar=calendar.id_calendar, **data.model_dump())
    db.add(activity)
    await db.flush()
    await ensure_deliveries_for_section_year(db, id_section_year)
    await db.commit()
    return to_public(activity, calendar)


async def update_activity(
    db, access, id_activity: int, data: ActivityUpdate
) -> ActivityPublic:
    activity = await get_activity(db, id_activity)
    calendar = activity.calendar
    if not access.can_manage(calendar.id_section_year):
        raise _forbidden()

    changes = data.model_fields_set
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No fields to update")

    due_date = (
        data.due_date
        if "due_date" in changes and data.due_date is not None
        else activity.due_date
    )
    _check_year(calendar, due_date)

    activity.due_date = due_date
    if "title" in changes:
        activity.title = data.title
    if "description" in changes:
        activity.description = data.description
    if "due_time" in changes:
        activity.due_time = data.due_time

    db.add(activity)
    await db.commit()
    return to_public(activity, calendar)


async def delete_activity(db, access, id_activity: int) -> None:
    activity = await get_activity(db, id_activity)
    if not access.can_manage(activity.calendar.id_section_year):
        raise _forbidden()
    if await has_delivery_data_for_activity(db, id_activity):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Activity has delivery data and cannot be deleted",
        )
    await db.delete(activity)
    await db.commit()


async def list_activities_for_calendar(
    db,
    id_calendar: int,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[Activity]:
    conditions = [Activity.id_calendar == id_calendar]
    if from_date is not None:
        conditions.append(Activity.due_date >= from_date)
    if to_date is not None:
        conditions.append(Activity.due_date <= to_date)
    rows = (
        await db.exec(
            select(Activity)
            .where(*conditions)
            .order_by(
                col(Activity.due_date),
                col(Activity.due_time),
                col(Activity.id_activity),
            )
        )
    ).all()
    return list(rows)


async def list_activities(
    db,
    user,
    access,
    id_section_year: int,
    *,
    from_date: date | None,
    to_date: date | None,
    limit: int,
    offset: int,
) -> tuple[list[Activity], int]:
    await get_section_year(db, id_section_year)
    await require_view_section_year(db, user, access, id_section_year)
    validate_optional_range(from_date, to_date)
    calendar = await ensure_calendar(db, id_section_year)

    conditions = [Activity.id_calendar == calendar.id_calendar]
    if from_date is not None:
        conditions.append(Activity.due_date >= from_date)
    if to_date is not None:
        conditions.append(Activity.due_date <= to_date)

    total = (
        await db.exec(
            select(func.count()).select_from(Activity).where(*conditions)
        )
    ).one()
    items = (
        await db.exec(
            select(Activity)
            .where(*conditions)
            .order_by(
                col(Activity.due_date),
                col(Activity.due_time),
                col(Activity.id_activity),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(items), total
