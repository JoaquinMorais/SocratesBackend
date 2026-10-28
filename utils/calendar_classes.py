from collections import defaultdict
from datetime import date, timedelta

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from models import Calendar, CalendarClass
from schemas.calendar_class import (
    CalendarClassBulkCreate,
    CalendarClassBulkUpdate,
    CalendarClassCreate,
    CalendarClassPublic,
    CalendarClassSelector,
    CalendarClassUpdate,
)
from utils.section_years import ensure_calendar, get_section_year

MAX_RANGE_DAYS = 366


def to_public(calendar_class: CalendarClass) -> CalendarClassPublic:
    return CalendarClassPublic(
        id_calendar_class=calendar_class.id_calendar_class,
        id_calendar=calendar_class.id_calendar,
        date=calendar_class.date,
        weekday=calendar_class.date.isoweekday(),
        start_time=calendar_class.start_time,
        end_time=calendar_class.end_time,
        modality=calendar_class.modality,
        title=calendar_class.title,
        location=calendar_class.location,
        meeting_url=calendar_class.meeting_url,
    )


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Calendar class not found")


def _forbidden() -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Only a professor of this section year or a super admin can do this",
    )


def _duplicate() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        "A class already starts at that time on that date",
    )


def _overlap() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        "This class overlaps another class in the calendar",
    )


def _invalid_range() -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "end_time must be after start_time",
    )


def _outside_year() -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Class dates must be in the section year",
    )


def _no_match() -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "No classes matched the selection",
    )


def _conflict(date_: date, detail: str) -> dict:
    return {"date": date_.isoformat(), "detail": detail}


async def get_calendar_class(db, id_calendar_class: int) -> CalendarClass:
    calendar_class = await db.get(CalendarClass, id_calendar_class)
    if not calendar_class:
        raise _not_found()
    return calendar_class


async def list_calendar_classes(
    db,
    id_calendar: int,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[CalendarClass]:
    conditions = [CalendarClass.id_calendar == id_calendar]
    if from_date is not None:
        conditions.append(CalendarClass.date >= from_date)
    if to_date is not None:
        conditions.append(CalendarClass.date <= to_date)
    rows = (
        await db.exec(
            select(CalendarClass)
            .where(*conditions)
            .order_by(
                col(CalendarClass.date),
                col(CalendarClass.start_time),
                col(CalendarClass.id_calendar_class),
            )
        )
    ).all()
    return list(rows)


async def _check_year(calendar: Calendar, date_: date) -> None:
    if date_.year != calendar.section_year.year:
        raise _outside_year()


async def _check_slot(
    db,
    id_calendar: int,
    date_: date,
    start_time,
    end_time,
    exclude_id: int | None = None,
) -> None:
    stmt = select(CalendarClass).where(
        CalendarClass.id_calendar == id_calendar,
        CalendarClass.date == date_,
    )
    if exclude_id is not None:
        stmt = stmt.where(CalendarClass.id_calendar_class != exclude_id)
    others = (await db.exec(stmt)).all()
    if any(other.start_time == start_time for other in others):
        raise _duplicate()
    if any(
        start_time < other.end_time and other.start_time < end_time
        for other in others
    ):
        raise _overlap()


async def create_calendar_class(
    db, access, id_section_year: int, data: CalendarClassCreate
) -> CalendarClassPublic:
    await get_section_year(db, id_section_year)
    if not access.can_manage(id_section_year):
        raise _forbidden()
    calendar = await ensure_calendar(db, id_section_year)
    await _check_year(calendar, data.date)
    await _check_slot(
        db, calendar.id_calendar, data.date, data.start_time, data.end_time
    )

    calendar_class = CalendarClass(id_calendar=calendar.id_calendar, **data.model_dump())
    db.add(calendar_class)
    try:
        await db.commit()
    except IntegrityError:  # altas simultáneas en la misma fecha y hora
        await db.rollback()
        raise _duplicate()
    return to_public(calendar_class)


async def update_calendar_class(
    db, access, id_calendar_class: int, data: CalendarClassUpdate
) -> CalendarClassPublic:
    calendar_class = await get_calendar_class(db, id_calendar_class)
    calendar = calendar_class.calendar
    if not access.can_manage(calendar.id_section_year):
        raise _forbidden()

    changes = data.model_fields_set
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No fields to update")

    date_ = (
        data.date
        if "date" in changes and data.date is not None
        else calendar_class.date
    )
    start_time = (
        data.start_time
        if "start_time" in changes and data.start_time is not None
        else calendar_class.start_time
    )
    end_time = (
        data.end_time
        if "end_time" in changes and data.end_time is not None
        else calendar_class.end_time
    )
    if end_time <= start_time:
        raise _invalid_range()
    await _check_year(calendar, date_)
    if (date_, start_time, end_time) != (
        calendar_class.date,
        calendar_class.start_time,
        calendar_class.end_time,
    ):
        await _check_slot(
            db,
            calendar.id_calendar,
            date_,
            start_time,
            end_time,
            exclude_id=id_calendar_class,
        )

    calendar_class.date = date_
    calendar_class.start_time = start_time
    calendar_class.end_time = end_time
    if "modality" in changes and data.modality is not None:
        calendar_class.modality = data.modality
    for field in ("title", "location", "meeting_url"):
        if field in changes:
            setattr(calendar_class, field, getattr(data, field))

    db.add(calendar_class)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise _duplicate()
    return to_public(calendar_class)


async def delete_calendar_class(db, access, id_calendar_class: int) -> None:
    calendar_class = await get_calendar_class(db, id_calendar_class)
    if not access.can_manage(calendar_class.calendar.id_section_year):
        raise _forbidden()
    await db.delete(calendar_class)
    await db.commit()


def _dates_between(from_date: date, to_date: date, weekdays: set[int]) -> list[date]:
    dates: list[date] = []
    day = from_date
    while day <= to_date:
        if day.isoweekday() in weekdays:
            dates.append(day)
        day += timedelta(days=1)
    return dates


async def bulk_create_calendar_classes(
    db, access, id_section_year: int, data: CalendarClassBulkCreate
) -> list[CalendarClassPublic]:
    section_year = await get_section_year(db, id_section_year)
    if not access.can_manage(id_section_year):
        raise _forbidden()
    if (
        data.from_date.year != section_year.year
        or data.to_date.year != section_year.year
    ):
        raise _outside_year()
    if (data.to_date - data.from_date).days > MAX_RANGE_DAYS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Date range is too long (max {MAX_RANGE_DAYS} days)",
        )

    calendar = await ensure_calendar(db, id_section_year)
    dates = _dates_between(data.from_date, data.to_date, set(data.weekdays))
    if not dates:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The selected range has no matching dates",
        )

    existing = (
        await db.exec(
            select(CalendarClass).where(
                CalendarClass.id_calendar == calendar.id_calendar,
                CalendarClass.date.in_(dates),
            )
        )
    ).all()
    conflicts = [
        _conflict(
            other.date,
            f"Overlaps an existing class ({other.start_time}-{other.end_time})",
        )
        for other in existing
        if data.start_time < other.end_time and other.start_time < data.end_time
    ]
    if conflicts:
        conflicts.sort(key=lambda conflict: conflict["date"])
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=conflicts,
        )

    created = [
        CalendarClass(
            id_calendar=calendar.id_calendar,
            date=date_,
            start_time=data.start_time,
            end_time=data.end_time,
            modality=data.modality,
            title=data.title,
            location=data.location,
            meeting_url=data.meeting_url,
        )
        for date_ in dates
    ]
    db.add_all(created)
    try:
        await db.commit()
    except IntegrityError:  # carreras con otra creación
        await db.rollback()
        raise _duplicate()
    return [to_public(calendar_class) for calendar_class in created]


async def _resolve_selection(
    db, calendar: Calendar, selector: CalendarClassSelector
) -> list[CalendarClass]:
    if selector.ids is not None:
        wanted = set(selector.ids)
        rows = (
            await db.exec(
                select(CalendarClass).where(
                    CalendarClass.id_calendar == calendar.id_calendar,
                    CalendarClass.id_calendar_class.in_(wanted),
                )
            )
        ).all()
        if {row.id_calendar_class for row in rows} != wanted:
            raise _not_found()
        return list(rows)

    filters = selector.filter
    rows = await list_calendar_classes(
        db,
        calendar.id_calendar,
        from_date=filters.from_date,
        to_date=filters.to_date,
    )
    if filters.weekdays is not None:
        weekdays = set(filters.weekdays)
        rows = [row for row in rows if row.date.isoweekday() in weekdays]
    return rows


def _overlaps_in_dates(slots: dict[date, list[tuple[int, object, object]]]) -> list[dict]:
    """Devuelve los conflictos por fecha entre intervalos [inicio, fin)."""
    conflicts: list[dict] = []
    for date_, day_slots in slots.items():
        day_slots.sort(key=lambda slot: (slot[1], slot[2]))
        for previous, current in zip(day_slots, day_slots[1:]):
            if previous[2] > current[1]:
                conflicts.append(
                    _conflict(
                        date_,
                        "The resulting classes overlap on that date",
                    )
                )
                break
    conflicts.sort(key=lambda conflict: conflict["date"])
    return conflicts


async def bulk_update_calendar_classes(
    db, access, id_section_year: int, data: CalendarClassBulkUpdate
) -> list[CalendarClassPublic]:
    await get_section_year(db, id_section_year)
    if not access.can_manage(id_section_year):
        raise _forbidden()
    calendar = await ensure_calendar(db, id_section_year)

    selected = await _resolve_selection(db, calendar, data)
    if not selected:
        raise _no_match()

    changes = data.changes
    change_fields = changes.model_fields_set
    selected_ids = {row.id_calendar_class for row in selected}

    resulting: dict[int, tuple[date, object, object]] = {}
    for row in selected:
        start_time = (
            changes.start_time
            if "start_time" in change_fields and changes.start_time is not None
            else row.start_time
        )
        end_time = (
            changes.end_time
            if "end_time" in change_fields and changes.end_time is not None
            else row.end_time
        )
        if end_time <= start_time:
            raise _invalid_range()
        resulting[row.id_calendar_class] = (row.date, start_time, end_time)

    others = (
        await db.exec(
            select(CalendarClass).where(
                CalendarClass.id_calendar == calendar.id_calendar,
                CalendarClass.id_calendar_class.notin_(selected_ids),
            )
        )
    ).all()
    slots: dict[date, list[tuple[int, object, object]]] = defaultdict(list)
    for other in others:
        slots[other.date].append(
            (other.id_calendar_class, other.start_time, other.end_time)
        )
    for id_calendar_class, (date_, start_time, end_time) in resulting.items():
        slots[date_].append((id_calendar_class, start_time, end_time))
    conflicts = _overlaps_in_dates(slots)
    if conflicts:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=conflicts)

    for row in selected:
        _, start_time, end_time = resulting[row.id_calendar_class]
        row.start_time = start_time
        row.end_time = end_time
        if "modality" in change_fields and changes.modality is not None:
            row.modality = changes.modality
        for field in ("title", "location", "meeting_url"):
            if field in change_fields:
                setattr(row, field, getattr(changes, field))
        db.add(row)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise _duplicate()
    return [to_public(row) for row in selected]


async def bulk_delete_calendar_classes(
    db, access, id_section_year: int, selector: CalendarClassSelector
) -> None:
    await get_section_year(db, id_section_year)
    if not access.can_manage(id_section_year):
        raise _forbidden()
    calendar = await ensure_calendar(db, id_section_year)

    selected = await _resolve_selection(db, calendar, selector)
    if not selected:
        raise _no_match()
    for row in selected:
        await db.delete(row)
    await db.commit()
