from datetime import date, datetime, time, timezone

from sqlmodel import select

from config.database import SessionLocal
from models import (
    Attendance,
    AttendanceSession,
    Calendar,
    CalendarClass,
    Project,
    StudentProject,
)
from tests.helpers import STUDENT, SUPER_ADMIN, assign_professor, create_cursada, section_year
from utils.security import hash_otp
from utils.statuses import get_status

URL = "/projects"
ANA_ID = 1
LUIS_ID = 2
LUIS = "100002@sistemas.frc.utn.edu.ar"


async def _project(client, headers, id_section_year: int) -> dict:
    r = await client.post(URL, json={"id_section_year": id_section_year}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def _membership(id_project: int, id_student: int, code: str, leader: bool = False):
    async with SessionLocal() as session:
        status = await get_status(session, "student_project", code)
        session.add(
            StudentProject(
                id_project=id_project,
                id_student=id_student,
                id_status=status.id_status,
                is_leader=leader,
            )
        )
        await session.commit()


async def _class_with_session(
    id_section_year: int,
    day: date,
    *,
    start: time = time(18, 30),
    end: time = time(20, 0),
) -> int:
    async with SessionLocal() as session:
        calendar = (
            await session.exec(
                select(Calendar).where(Calendar.id_section_year == id_section_year)
            )
        ).one()
        calendar_class = CalendarClass(
            id_calendar=calendar.id_calendar,
            date=day,
            start_time=start,
            end_time=end,
            modality="in_person",
        )
        session.add(calendar_class)
        await session.flush()
        start_at = datetime.combine(day, start).replace(tzinfo=timezone.utc)
        session.add(
            AttendanceSession(
                id_calendar_class=calendar_class.id_calendar_class,
                code_hash=hash_otp("000000"),
                opened_at=start_at,
                expires_at=start_at,
            )
        )
        await session.commit()
        return calendar_class.id_calendar_class


async def _mark(id_student_section_year: int, id_calendar_class: int, method: str = "code"):
    async with SessionLocal() as session:
        session.add(
            Attendance(
                id_student_section_year=id_student_section_year,
                id_calendar_class=id_calendar_class,
                method=method,
            )
        )
        await session.commit()


async def _attendance(client, headers, id_project: int, **params):
    return await client.get(f"{URL}/{id_project}/attendance", params=params, headers=headers)


async def test_project_attendance_permissions(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2025)
    project = await _project(client, admin, sy)
    await _membership(project["id_project"], ANA_ID, "active", leader=True)

    assert (await client.get(f"{URL}/{project['id_project']}/attendance")).status_code == 401
    assert (
        await _attendance(client, await login(STUDENT), project["id_project"])
    ).status_code == 403

    other = await make_professor("prof-att-project@frc.utn.edu.ar")
    assert (
        await _attendance(client, await login(other), project["id_project"])
    ).status_code == 403

    assigned = await make_professor("prof-att-project-ok@frc.utn.edu.ar", legajo=300004)
    await assign_professor(client, admin, assigned, sy)
    assert (
        await _attendance(client, await login(assigned), project["id_project"])
    ).status_code == 200
    assert (
        await _attendance(client, admin, project["id_project"])
    ).status_code == 200
    assert (await _attendance(client, admin, 999)).status_code == 404


async def test_project_attendance_counts_and_percentages(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2025)
    project = await _project(client, admin, sy)
    await _membership(project["id_project"], ANA_ID, "active", leader=True)
    await _membership(project["id_project"], LUIS_ID, "active")
    ana = await create_cursada(ANA_ID, sy)
    luis = await create_cursada(LUIS_ID, sy)

    first = await _class_with_session(sy, date(2025, 3, 3))
    second = await _class_with_session(sy, date(2025, 3, 10))
    third = await _class_with_session(sy, date(2025, 3, 17))
    for class_id in (first, second):
        await _mark(ana.id_student_section_year, class_id)
    await _mark(luis.id_student_section_year, first)

    body = (await _attendance(client, admin, project["id_project"])).json()
    by_student = {item["id_student"]: item for item in body["items"]}
    assert by_student[ANA_ID]["attendance"] == {
        "attended_classes": 2,
        "total_classes": 3,
        "attendance_percentage": 66.67,
    }
    assert by_student[LUIS_ID]["attendance"] == {
        "attended_classes": 1,
        "total_classes": 3,
        "attendance_percentage": 33.33,
    }
    assert body["id_section_year"] == sy
    assert body["total"] == 2


async def test_project_attendance_range(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2025)
    project = await _project(client, admin, sy)
    await _membership(project["id_project"], ANA_ID, "active", leader=True)
    ana = await create_cursada(ANA_ID, sy)

    first = await _class_with_session(sy, date(2025, 3, 3))
    second = await _class_with_session(sy, date(2025, 3, 10))
    await _class_with_session(sy, date(2025, 3, 17))
    await _mark(ana.id_student_section_year, first)

    body = (
        await _attendance(
            client,
            admin,
            project["id_project"],
            **{"from": "2025-03-01", "to": "2025-03-10"},
        )
    ).json()
    assert body["items"][0]["attendance"] == {
        "attended_classes": 1,
        "total_classes": 2,
        "attendance_percentage": 50.0,
    }


async def test_project_attendance_without_sessions_and_status_filter(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2025)
    project = await _project(client, admin, sy)
    await _membership(project["id_project"], ANA_ID, "active", leader=True)
    await _membership(project["id_project"], LUIS_ID, "abandoned")
    await create_cursada(ANA_ID, sy)
    await create_cursada(LUIS_ID, sy, state="abandoned")

    body = (await _attendance(client, admin, project["id_project"])).json()
    assert [item["id_student"] for item in body["items"]] == [ANA_ID]
    assert body["items"][0]["attendance"]["total_classes"] == 0
    assert body["items"][0]["attendance"]["attendance_percentage"] is None

    body = (
        await _attendance(client, admin, project["id_project"], status="abandoned")
    ).json()
    assert [item["id_student"] for item in body["items"]] == [LUIS_ID]
    assert body["items"][0]["attendance"] is not None


async def test_project_attendance_does_not_mix_section_years(client, login):
    admin = await login(SUPER_ADMIN)
    sy_2025 = await section_year(client, admin, "3K1", 2025)
    sy_2026 = await section_year(client, admin, "3K2", 2026)
    project = await _project(client, admin, sy_2025)
    await _membership(project["id_project"], ANA_ID, "active", leader=True)
    ana_2025 = await create_cursada(ANA_ID, sy_2025)
    ana_2026 = await create_cursada(ANA_ID, sy_2026, state="finished_approved")

    class_2025 = await _class_with_session(sy_2025, date(2025, 3, 3))
    class_2026 = await _class_with_session(sy_2026, date(2026, 3, 3))
    await _mark(ana_2025.id_student_section_year, class_2025)
    await _mark(ana_2026.id_student_section_year, class_2026)

    body = (await _attendance(client, admin, project["id_project"])).json()
    assert body["items"][0]["attendance"] == {
        "attended_classes": 1,
        "total_classes": 1,
        "attendance_percentage": 100.0,
    }


async def test_project_attendance_invalid_filters(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2025)
    project = await _project(client, admin, sy)

    assert (
        await _attendance(client, admin, project["id_project"], status="nope")
    ).status_code == 422
    assert (
        await _attendance(
            client, admin, project["id_project"], **{"from": "2025-03-10"}
        )
    ).status_code == 422
    assert (
        await _attendance(
            client, admin, project["id_project"], **{"from": "2025-03-10", "to": "2025-03-01"}
        )
    ).status_code == 422
