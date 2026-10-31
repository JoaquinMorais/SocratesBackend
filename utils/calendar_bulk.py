from collections import defaultdict
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from models import Activity, CalendarClass
from schemas.calendar_bulk import CalendarBulkLoad, CalendarBulkLoadReport
from utils.deliveries import ensure_deliveries_for_section_year
from utils.section_years import ensure_calendar, get_section_year


def _forbidden() -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Only a professor of this section year or a super admin can do this",
    )


def _row(kind: str, row: int, detail: str) -> dict:
    return {"kind": kind, "row": row, "detail": detail}


async def bulk_load_calendar(
    db,
    access,
    id_section_year: int,
    data: CalendarBulkLoad,
    *,
    dry_run: bool,
) -> CalendarBulkLoadReport:
    section_year = await get_section_year(db, id_section_year)
    if not access.can_manage(id_section_year):
        raise _forbidden()
    calendar = await ensure_calendar(db, id_section_year)

    errors: list[dict] = []

    for row, calendar_class in enumerate(data.classes, start=1):
        if calendar_class.date.year != section_year.year:
            errors.append(
                _row(
                    "class",
                    row,
                    "Class date must be in the section year",
                )
            )
    for row, activity in enumerate(data.activities, start=1):
        if activity.due_date.year != section_year.year:
            errors.append(
                _row(
                    "activity",
                    row,
                    "Activity date must be in the section year",
                )
            )

    # Choques dentro del propio payload (solo entre clases).
    by_date: dict[date, list[tuple[int, object, object]]] = defaultdict(list)
    for row, calendar_class in enumerate(data.classes, start=1):
        by_date[calendar_class.date].append(
            (row, calendar_class.start_time, calendar_class.end_time)
        )
    for date_, slots in by_date.items():
        slots.sort(key=lambda slot: (slot[1], slot[2], slot[0]))
        for previous, current in zip(slots, slots[1:]):
            if previous[2] > current[1]:
                errors.append(
                    _row(
                        "class",
                        current[0],
                        f"Overlaps another class on {date_.isoformat()}",
                    )
                )

    if errors:
        errors.sort(key=lambda error: (error["kind"], error["row"]))
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=errors
        )

    # Choques contra las clases que ya están en el calendario.
    dates = {calendar_class.date for calendar_class in data.classes}
    existing = (
        []
        if not dates
        else (
            await db.exec(
                select(CalendarClass).where(
                    CalendarClass.id_calendar == calendar.id_calendar,
                    CalendarClass.date.in_(dates),
                )
            )
        ).all()
    )
    existing_by_date: dict[date, list[CalendarClass]] = defaultdict(list)
    for calendar_class in existing:
        existing_by_date[calendar_class.date].append(calendar_class)

    conflicts: list[dict] = []
    for row, calendar_class in enumerate(data.classes, start=1):
        for other in existing_by_date.get(calendar_class.date, []):
            if (
                calendar_class.start_time < other.end_time
                and other.start_time < calendar_class.end_time
            ):
                conflicts.append(
                    _row(
                        "class",
                        row,
                        f"Overlaps an existing class on "
                        f"{calendar_class.date.isoformat()} "
                        f"({other.start_time}-{other.end_time})",
                    )
                )
                break
    if conflicts:
        conflicts.sort(key=lambda conflict: conflict["row"])
        raise HTTPException(status.HTTP_409_CONFLICT, detail=conflicts)

    if dry_run:
        return CalendarBulkLoadReport(
            dry_run=True,
            classes_created=len(data.classes),
            activities_created=len(data.activities),
        )

    created_classes = [
        CalendarClass(id_calendar=calendar.id_calendar, **calendar_class.model_dump())
        for calendar_class in data.classes
    ]
    created_activities = [
        Activity(id_calendar=calendar.id_calendar, **activity.model_dump())
        for activity in data.activities
    ]
    db.add_all([*created_classes, *created_activities])
    await db.flush()
    await ensure_deliveries_for_section_year(db, id_section_year)
    try:
        await db.commit()
    except IntegrityError:  # el calendario cambió entre la validación y el commit
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The calendar changed while loading; please retry",
        )

    return CalendarBulkLoadReport(
        dry_run=False,
        classes_created=len(created_classes),
        activities_created=len(created_activities),
    )
