from datetime import date, datetime, time, timezone

from sqlmodel import select

from config.database import SessionLocal
from models import (
    Attendance,
    AttendanceSession,
    Calendar,
    CalendarClass,
    StudentProject,
)
from tests.helpers import (
    STUDENT,
    SUPER_ADMIN,
    assign_professor,
    create_cursada,
    section_year,
)
from utils.security import hash_otp
from utils.statuses import get_status

ANA_ID, LUIS_ID = 1, 2
URL = "/students/statistics"
ANA = "100001@sistemas.frc.utn.edu.ar"


async def _register(client, headers, id_student: int, id_section_year: int):
    return await client.post(
        "/student-section-years",
        json={"id_student": id_student, "id_section_year": id_section_year},
        headers=headers,
    )


async def _membership(id_project: int, id_student: int, code: str = "active"):
    async with SessionLocal() as session:
        membership_status = await get_status(session, "student_project", code)
        session.add(
            StudentProject(
                id_project=id_project,
                id_student=id_student,
                id_status=membership_status.id_status,
            )
        )
        await session.commit()


async def _project(client, admin, id_section_year: int) -> dict:
    r = await client.post(
        "/projects", json={"id_section_year": id_section_year}, headers=admin
    )
    assert r.status_code == 201, r.text
    return r.json()


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


async def _stats(client, headers, population: str, **params):
    return await client.get(
        f"{URL}/{population}", params=params, headers=headers
    )


async def test_requires_authentication(client):
    assert (await client.get(f"{URL}/registered")).status_code == 401
    assert (await client.get(f"{URL}/attending")).status_code == 401


async def test_student_cannot_read(client, login):
    headers = await login(STUDENT)
    assert (await _stats(client, headers, "registered")).status_code == 403
    assert (await _stats(client, headers, "attending")).status_code == 403


async def test_registered_statistics(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2026)
    project = await _project(client, admin, sy)
    await _membership(project["id_project"], ANA_ID, "active")
    assert (await _register(client, admin, ANA_ID, sy)).status_code == 201
    assert (await _register(client, admin, LUIS_ID, sy)).status_code == 201

    body = (await _stats(client, admin, "registered")).json()
    assert body["population"] == "registered"
    assert body["total"] == 2
    stats = body["statistics"]
    assert stats["students_total"] == 2
    assert stats["section_years_total"] == 1
    assert stats["with_project"] == 1
    assert stats["without_project"] == 1
    assert stats["memberships_by_status"]["active"] == 1
    assert stats["attendance"] == {
        "members_with_attendance": 0,
        "attended_classes": 0,
        "total_classes": 0,
        "attendance_percentage": None,
    }
    assert body["by_section_year"][0]["students_total"] == 2
    assert body["by_section_year"][0]["with_project"] == 1
    assert body["by_section_year"][0]["without_project"] == 1
    assert {item["id_student"] for item in body["items"]} == {ANA_ID, LUIS_ID}
    by_student = {item["id_student"]: item for item in body["items"]}
    assert by_student[ANA_ID]["with_project"] is True
    assert by_student[LUIS_ID]["with_project"] is False
    assert by_student[ANA_ID]["section_years"][0]["attendance"] is None
    assert by_student[ANA_ID]["project_memberships"][0]["status"]["code"] == "active"

    page = (await _stats(client, admin, "registered", limit=1)).json()
    assert page["total"] == 2 and len(page["items"]) == 1


async def test_attending_statistics(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2026)
    project = await _project(client, admin, sy)
    await _membership(project["id_project"], ANA_ID, "active")
    ana = await create_cursada(ANA_ID, sy)
    luis = await create_cursada(LUIS_ID, sy)
    first = await _class_with_session(sy, date(2026, 3, 3))
    second = await _class_with_session(sy, date(2026, 3, 10))
    await _mark(ana.id_student_section_year, first)
    await _mark(ana.id_student_section_year, second)
    await _mark(luis.id_student_section_year, first)

    body = (await _stats(client, admin, "attending")).json()
    assert body["total"] == 2
    stats = body["statistics"]
    assert stats["with_project"] == 1
    assert stats["without_project"] == 1
    assert stats["attendance"] == {
        "members_with_attendance": 2,
        "attended_classes": 3,
        "total_classes": 4,
        "attendance_percentage": 75.0,
    }
    by_student = {item["id_student"]: item for item in body["items"]}
    assert by_student[ANA_ID]["section_years"][0]["attendance"] == {
        "attended_classes": 2,
        "total_classes": 2,
        "attendance_percentage": 100.0,
    }
    assert by_student[LUIS_ID]["section_years"][0]["attendance"] == {
        "attended_classes": 1,
        "total_classes": 2,
        "attendance_percentage": 50.0,
    }


async def test_filters_and_professor_scope(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sy_a = await section_year(client, admin, "3K1", 2026)
    sy_b = await section_year(client, admin, "3K2", 2026)
    assert (await _register(client, admin, ANA_ID, sy_a)).status_code == 201
    assert (await _register(client, admin, LUIS_ID, sy_b)).status_code == 201

    mail = await make_professor("prof-student-stats@frc.utn.edu.ar")
    await assign_professor(client, admin, mail, sy_a)
    headers = await login(mail)
    body = (await _stats(client, headers, "registered")).json()
    assert body["total"] == 1
    assert body["items"][0]["id_student"] == ANA_ID
    assert (
        await _stats(client, headers, "registered", id_section_year=sy_a)
    ).status_code == 200
    assert (
        await _stats(client, headers, "registered", id_section_year=sy_b)
    ).status_code == 403

    all_body = (await _stats(client, admin, "registered")).json()
    assert all_body["total"] == 2
    filtered = (
        await _stats(client, admin, "registered", id_section_year=sy_b)
    ).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["id_student"] == LUIS_ID


async def test_unknown_section_year(client, login):
    assert (
        await _stats(
            client,
            await login(SUPER_ADMIN),
            "registered",
            id_section_year=999999,
        )
    ).status_code == 404
