from datetime import date

from sqlmodel import col, select

from models import Activity, Calendar, CalendarClass
from schemas.calendar import CalendarPublic, CalendarWithClassesPublic
from schemas.me_calendar import MyCalendarPublic
from utils.activities import list_activities_for_calendar
from utils.activities import to_public as activity_public
from utils.calendar_classes import list_calendar_classes
from utils.calendar_classes import to_public as class_public
from utils.date_ranges import validate_optional_range
from utils.projects import current_section_years
from utils.section_years import (
    ensure_calendar,
    get_section_year,
    require_view_section_year,
    to_public as section_year_public,
)


def to_public(calendar: Calendar) -> CalendarPublic:
    return CalendarPublic(
        id_calendar=calendar.id_calendar,
        id_section_year=calendar.id_section_year,
        timezone=calendar.timezone,
    )


async def get_calendar_with_classes(
    db,
    user,
    access,
    id_section_year: int,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> CalendarWithClassesPublic:
    await get_section_year(db, id_section_year)
    await require_view_section_year(db, user, access, id_section_year)
    validate_optional_range(from_date, to_date)
    calendar = await ensure_calendar(db, id_section_year)

    classes = await list_calendar_classes(
        db, calendar.id_calendar, from_date=from_date, to_date=to_date
    )
    activities = await list_activities_for_calendar(
        db, calendar.id_calendar, from_date=from_date, to_date=to_date
    )
    return CalendarWithClassesPublic(
        id_calendar=calendar.id_calendar,
        id_section_year=calendar.id_section_year,
        timezone=calendar.timezone,
        classes=[class_public(calendar_class) for calendar_class in classes],
        activities=[activity_public(activity, calendar) for activity in activities],
    )


async def get_my_calendar(
    db,
    user,
    access,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> MyCalendarPublic:
    """Clases y actividades de los cursos actuales del usuario (año máximo)."""
    validate_optional_range(from_date, to_date)

    years = await current_section_years(db, user, access)
    if not years:
        return MyCalendarPublic()

    calendars = [
        await ensure_calendar(db, section_year.id_section_year) for section_year in years
    ]
    calendar_ids = [calendar.id_calendar for calendar in calendars]

    class_conditions = [CalendarClass.id_calendar.in_(calendar_ids)]
    activity_conditions = [Activity.id_calendar.in_(calendar_ids)]
    if from_date is not None:
        class_conditions.append(CalendarClass.date >= from_date)
        class_conditions.append(CalendarClass.date <= to_date)
        activity_conditions.append(Activity.due_date >= from_date)
        activity_conditions.append(Activity.due_date <= to_date)

    classes = (
        await db.exec(
            select(CalendarClass)
            .where(*class_conditions)
            .order_by(
                col(CalendarClass.date),
                col(CalendarClass.start_time),
                col(CalendarClass.id_calendar_class),
            )
        )
    ).all()
    activities = (
        await db.exec(
            select(Activity)
            .where(*activity_conditions)
            .order_by(
                col(Activity.due_date),
                col(Activity.due_time),
                col(Activity.id_activity),
            )
        )
    ).all()
    calendar_by_id = {calendar.id_calendar: calendar for calendar in calendars}

    return MyCalendarPublic(
        section_years=[section_year_public(section_year) for section_year in years],
        classes=[class_public(calendar_class) for calendar_class in classes],
        activities=[
            activity_public(activity, calendar_by_id[activity.id_calendar])
            for activity in activities
        ],
    )
