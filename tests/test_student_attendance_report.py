from datetime import date, datetime, time, timezone

from sqlmodel import select

from config.database import SessionLocal
from models import Attendance, AttendanceSession, Calendar, CalendarClass
from tests.helpers import (
    STUDENT,
    SUPER_ADMIN,
    assign_professor,
    create_cursada,
    section_year,
)
from utils.security import hash_otp

ANA_ID = 1
ANA = "100001@sistemas.frc.utn.edu.ar"
URL = f"/students/{ANA_ID}/attendance"


async def _class_with_session(id_section_year: int, day: date) -> int:
    async with SessionLocal() as session:
        calendar = (
            await session.exec(
                select(Calendar).where(Calendar.id_section_year == id_section_year)
            )
        ).one()
        calendar_class = CalendarClass(
            id_calendar=calendar.id_calendar,
            date=day,
            start_time=time(18, 30),
            end_time=time(20, 0),
            modality="in_person",
        )
        session.add(calendar_class)
        await session.flush()
        start = datetime.combine(day, time(18, 30)).replace(tzinfo=timezone.utc)
        session.add(
            AttendanceSession(
                id_calendar_class=calendar_class.id_calendar_class,
                code_hash=hash_otp("000000"),
                opened_at=start,
                expires_at=start,
            )
        )
        await session.commit()
        return calendar_class.id_calendar_class


async def _mark(id_student_section_year: int, id_calendar_class: int) -> None:
    async with SessionLocal() as session:
        session.add(
            Attendance(
                id_student_section_year=id_student_section_year,
                id_calendar_class=id_calendar_class,
                method="manual",
            )
        )
        await session.commit()


async def _setup(client, admin, make_professor):
    sy_a = await section_year(client, admin, "3K1", 2026)
    sy_b = await section_year(client, admin, "3K2", 2026)
    cursada_a = await create_cursada(ANA_ID, sy_a)
    cursada_b = await create_cursada(ANA_ID, sy_b, state="finished_failed")
    class_a = await _class_with_session(sy_a, date(2026, 3, 3))
    class_b = await _class_with_session(sy_b, date(2026, 3, 10))
    await _mark(cursada_a.id_student_section_year, class_a)
    await _mark(cursada_b.id_student_section_year, class_b)
    mail = await make_professor("prof-student-attendance@frc.utn.edu.ar")
    await assign_professor(client, admin, mail, sy_a)
    return {"sy_a": sy_a, "sy_b": sy_b, "mail": mail}


async def _report(client, headers, **params):
    return await client.get(URL, params=params, headers=headers)


async def test_requires_authentication(client):
    assert (await client.get(URL)).status_code == 401


async def test_student_cannot_read(client, login):
    assert (await _report(client, await login(STUDENT))).status_code == 403


async def test_unassigned_professor_cannot_read(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    await _setup(client, admin, make_professor)
    other = await login(await make_professor("prof-student-att-other@frc.utn.edu.ar"))
    assert (await _report(client, other)).status_code == 403


async def test_assigned_professor_only_sees_own_course(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    body = (await _report(client, await login(ctx["mail"]))).json()
    assert [item["id_section_year"] for item in body["section_years"]] == [
        ctx["sy_a"]
    ]
    assert len(body["items"]) == 1
    assert body["items"][0]["id_section_year"] == ctx["sy_a"]
    assert body["section_years"][0]["attendance"] == {
        "attended_classes": 1,
        "total_classes": 1,
        "attendance_percentage": 100.0,
    }


async def test_super_admin_sees_all_courses_and_filters(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    body = (await _report(client, admin)).json()
    assert {item["id_section_year"] for item in body["section_years"]} == {
        ctx["sy_a"],
        ctx["sy_b"],
    }
    assert len(body["items"]) == 2
    filtered = (
        await _report(
            client,
            admin,
            **{"from": "2026-03-01", "to": "2026-03-05"},
        )
    ).json()
    assert len(filtered["items"]) == 1
    assert filtered["items"][0]["id_section_year"] == ctx["sy_a"]
    assert (
        await _report(client, admin, **{"from": "2026-03-01"})
    ).status_code == 422
    assert (
        await _report(
            client,
            admin,
            **{"from": "2026-03-10", "to": "2026-03-01"},
        )
    ).status_code == 422
    assert (await _report(client, admin, **{"from": "2025-01-01", "to": "2026-03-01"})).status_code == 422


async def test_unknown_student_returns_404(client, login):
    assert (
        await client.get("/students/999999/attendance", headers=await login(SUPER_ADMIN))
    ).status_code == 404
