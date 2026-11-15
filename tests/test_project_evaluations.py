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

URL = "/projects"
ANA_ID, LUIS_ID = 1, 2
ANA = "100001@sistemas.frc.utn.edu.ar"
LUIS = "100002@sistemas.frc.utn.edu.ar"


async def _membership(
    id_project: int,
    id_student: int,
    code: str = "active",
    *,
    is_leader: bool = False,
) -> None:
    async with SessionLocal() as session:
        membership_status = await get_status(session, "student_project", code)
        session.add(
            StudentProject(
                id_project=id_project,
                id_student=id_student,
                id_status=membership_status.id_status,
                is_leader=is_leader,
            )
        )
        await session.commit()


async def _project(client, admin, id_section_year: int) -> dict:
    r = await client.post(
        URL, json={"id_section_year": id_section_year}, headers=admin
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _activity(client, admin, id_section_year: int, title: str, due: str) -> dict:
    r = await client.post(
        f"/section-years/{id_section_year}/activities",
        json={"title": title, "due_date": due},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _delivery_id(client, admin, id_project: int, id_activity: int) -> int:
    body = (
        await client.get(f"{URL}/{id_project}/deliveries", headers=admin)
    ).json()
    return next(
        item["id_delivery"]
        for item in body["items"]
        if item["id_activity"] == id_activity
    )


async def _scores(client, admin, id_section_year: int) -> dict[str, dict]:
    r = await client.get(
        f"/section-years/{id_section_year}/scores", headers=admin
    )
    assert r.status_code == 200, r.text
    return {item["code"]: item for item in r.json()["items"]}


async def _grade(client, admin, id_delivery: int, category: str, id_score: int):
    return await client.post(
        f"/deliveries/{id_delivery}/grades",
        json={"category": category, "id_score": id_score},
        headers=admin,
    )


async def _class_with_session(
    id_section_year: int, day: date, *, start: time = time(18, 30)
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
            end_time=time(20, 0),
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


async def _setup(client, admin, make_professor, *, assigned: bool = True):
    sy = await section_year(client, admin, "3K1", 2026)
    project = await _project(client, admin, sy)
    first_activity = await _activity(client, admin, sy, "Primera", "2026-03-10")
    second_activity = await _activity(client, admin, sy, "Segunda", "2026-04-10")
    await _membership(
        project["id_project"], ANA_ID, "active", is_leader=True
    )
    await _membership(project["id_project"], LUIS_ID, "finished")
    ana_cursada = await create_cursada(ANA_ID, sy)
    luis_cursada = await create_cursada(LUIS_ID, sy, state="finished_approved")
    mail = await make_professor("prof-evaluations@frc.utn.edu.ar")
    if assigned:
        await assign_professor(client, admin, mail, sy)
    return {
        "sy": sy,
        "project": project,
        "first_activity": first_activity,
        "second_activity": second_activity,
        "first_delivery": await _delivery_id(
            client, admin, project["id_project"], first_activity["id_activity"]
        ),
        "second_delivery": await _delivery_id(
            client, admin, project["id_project"], second_activity["id_activity"]
        ),
        "ana_cursada": ana_cursada,
        "luis_cursada": luis_cursada,
        "professor_mail": mail,
    }


async def _evaluation(client, headers, id_project: int):
    return await client.get(f"{URL}/{id_project}/evaluations", headers=headers)


# ---------- permisos ----------
async def test_requires_authentication(client):
    assert (await client.get(f"{URL}/1/evaluations")).status_code == 401


async def test_student_and_unassigned_professor_forbidden(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor, assigned=False)
    assert (
        await _evaluation(client, await login(ANA), ctx["project"]["id_project"])
    ).status_code == 403
    assert (
        await _evaluation(
            client, await login(ctx["professor_mail"]), ctx["project"]["id_project"]
        )
    ).status_code == 403


async def test_assigned_professor_and_super_admin_can_read(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    assert (
        await _evaluation(client, await login(ctx["professor_mail"]), ctx["project"]["id_project"])
    ).status_code == 200
    assert (
        await _evaluation(client, admin, ctx["project"]["id_project"])
    ).status_code == 200


async def test_unknown_project(client, login):
    assert (
        await _evaluation(
            client, await login(SUPER_ADMIN), 999999
        )
    ).status_code == 404


# ---------- evaluación completa ----------
async def test_evaluation_includes_activities_grades_members_and_statistics(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    scores = await _scores(client, admin, ctx["sy"])

    first_class = await _class_with_session(ctx["sy"], date(2026, 3, 3))
    second_class = await _class_with_session(ctx["sy"], date(2026, 3, 10))
    await _mark(ctx["ana_cursada"].id_student_section_year, first_class)
    await _mark(ctx["ana_cursada"].id_student_section_year, second_class)
    await _mark(ctx["luis_cursada"].id_student_section_year, first_class)

    assert (
        await _grade(
            client, admin, ctx["first_delivery"], "activity", scores["good"]["id_score"]
        )
    ).status_code == 201
    assert (
        await _grade(
            client, admin, ctx["first_delivery"], "activity", scores["excellent"]["id_score"]
        )
    ).status_code == 201
    assert (
        await _grade(
            client, admin, ctx["first_delivery"], "follow_up", scores["regular"]["id_score"]
        )
    ).status_code == 201
    assert (
        await _grade(
            client, admin, ctx["second_delivery"], "activity", scores["very_good"]["id_score"]
        )
    ).status_code == 201

    body = (await _evaluation(client, admin, ctx["project"]["id_project"])).json()
    assert body["project"]["status"]["code"] == "uninsured"
    assert body["project"]["id_project"] == ctx["project"]["id_project"]
    assert [item["activity"]["title"] for item in body["activities"]] == [
        "Primera",
        "Segunda",
    ]
    assert all(item["status"]["code"] == "requested" for item in body["activities"])
    first = body["activities"][0]
    second = body["activities"][1]
    assert len(first["grades"]) == 3
    assert {item["category"] for item in first["latest_grades"]} == {
        "activity",
        "follow_up",
    }
    assert len(second["grades"]) == 1
    assert len(second["latest_grades"]) == 1

    stats = body["statistics"]
    assert stats["deliveries_total"] == 2
    assert stats["deliveries_with_link"] == 0
    assert stats["graded_deliveries"] == 2
    assert stats["grades_total"] == 4
    assert stats["latest_grades_total"] == 3
    assert stats["average_latest"] == 78.33
    assert stats["average_all"] == 75.0
    assert stats["average_latest_activity"] == 90.0
    assert stats["average_latest_follow_up"] == 55.0
    assert stats["attendance"] == {
        "attended_classes": 3,
        "total_classes": 4,
        "attendance_percentage": 75.0,
    }
    assert stats["members_total"] == 2
    assert stats["members_active"] == 1
    assert stats["members_finished"] == 1

    members = {item["id_student"]: item for item in body["members"]}
    assert members[ANA_ID]["status"]["code"] == "active"
    assert members[ANA_ID]["is_leader"] is True
    assert members[ANA_ID]["attendance"] == {
        "attended_classes": 2,
        "total_classes": 2,
        "attendance_percentage": 100.0,
    }
    assert members[LUIS_ID]["status"]["code"] == "finished"
    assert members[LUIS_ID]["attendance"] == {
        "attended_classes": 1,
        "total_classes": 2,
        "attendance_percentage": 50.0,
    }
    assert "email" not in members[ANA_ID]


async def test_evaluation_without_grades_or_attendance(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)

    body = (await _evaluation(client, admin, ctx["project"]["id_project"])).json()
    stats = body["statistics"]
    assert stats["deliveries_total"] == 2
    assert stats["graded_deliveries"] == 0
    assert stats["grades_total"] == 0
    assert stats["latest_grades_total"] == 0
    assert stats["average_latest"] is None
    assert stats["average_all"] is None
    assert stats["average_latest_activity"] is None
    assert stats["average_latest_follow_up"] is None
    assert stats["attendance"] == {
        "attended_classes": 0,
        "total_classes": 0,
        "attendance_percentage": None,
    }
    assert all(item["grades"] == [] for item in body["activities"])
