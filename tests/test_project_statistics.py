from datetime import date, datetime, time, timezone

from sqlmodel import select

from config.database import SessionLocal
from models import (
    Attendance,
    AttendanceSession,
    Calendar,
    CalendarClass,
    Student,
    StudentProject,
    User,
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


async def _membership(id_project: int, id_student: int, code: str, *, leader=False):
    async with SessionLocal() as session:
        membership_status = await get_status(session, "student_project", code)
        session.add(
            StudentProject(
                id_project=id_project,
                id_student=id_student,
                id_status=membership_status.id_status,
                is_leader=leader,
            )
        )
        await session.commit()


async def _new_member(id_project: int, legajo: int, code: str) -> int:
    async with SessionLocal() as session:
        user = User(
            first_name="Extra",
            last_name=f"Alumno {legajo}",
            legajo=legajo,
            birth_date=date(2003, 1, 1),
        )
        user.set_password("Test1234!")
        session.add(user)
        await session.flush()
        session.add(Student(id_student=user.id_user, enrollment_year=2021))
        membership_status = await get_status(session, "student_project", code)
        session.add(
            StudentProject(
                id_project=id_project,
                id_student=user.id_user,
                id_status=membership_status.id_status,
            )
        )
        await session.commit()
        return user.id_user


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


async def _action(client, headers, id_delivery: int, action: str):
    return await client.post(
        f"/deliveries/{id_delivery}/{action}", headers=headers
    )


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


async def _create_comment(client, headers, id_delivery: int, content: str, kind="feedback"):
    return await client.post(
        f"/deliveries/{id_delivery}/comments",
        json={"content": content, "kind": kind},
        headers=headers,
    )


async def _add_technology(client, headers, id_project: int, name: str) -> dict:
    r = await client.post("/technologies", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    technology = r.json()
    r = await client.post(
        f"{URL}/{id_project}/technologies",
        json={"id_technology": technology["id_technology"]},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return technology


async def _setup(client, admin, make_professor, *, assigned: bool = True):
    sy = await section_year(client, admin, "3K1", 2026)
    project = await _project(client, admin, sy)
    first_activity = await _activity(client, admin, sy, "Primera", "2026-03-10")
    second_activity = await _activity(client, admin, sy, "Segunda", "2026-04-10")
    await _membership(project["id_project"], ANA_ID, "active", leader=True)
    await _membership(project["id_project"], LUIS_ID, "finished")
    for legajo, code in (
        (900101, "pending_approval"),
        (900102, "abandoned"),
        (900103, "expelled"),
        (900104, "rejected"),
    ):
        await _new_member(project["id_project"], legajo, code)
    ana_cursada = await create_cursada(ANA_ID, sy)
    luis_cursada = await create_cursada(LUIS_ID, sy, state="finished_approved")
    mail = await make_professor("prof-statistics@frc.utn.edu.ar")
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
        "mail": mail,
    }


async def _statistics(client, headers, id_project: int):
    return await client.get(f"{URL}/{id_project}/statistics", headers=headers)


# ---------- permisos ----------
async def test_requires_authentication(client):
    assert (await client.get(f"{URL}/1/statistics")).status_code == 401


async def test_student_and_unassigned_professor_forbidden(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor, assigned=False)
    assert (
        await _statistics(client, await login(ANA), ctx["project"]["id_project"])
    ).status_code == 403
    assert (
        await _statistics(
            client, await login(ctx["mail"]), ctx["project"]["id_project"]
        )
    ).status_code == 403


async def test_assigned_professor_and_super_admin_can_read(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    assert (
        await _statistics(
            client, await login(ctx["mail"]), ctx["project"]["id_project"]
        )
    ).status_code == 200
    assert (
        await _statistics(client, admin, ctx["project"]["id_project"])
    ).status_code == 200


async def test_unknown_project(client, login):
    assert (
        await _statistics(client, await login(SUPER_ADMIN), 999999)
    ).status_code == 404


async def test_empty_project_statistics(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2026)
    project = await _project(client, admin, sy)
    body = (await _statistics(client, admin, project["id_project"])).json()
    stats = body["statistics"]
    assert stats["activities_total"] == 0
    assert stats["members_total"] == 0
    assert stats["grades_total"] == 0
    assert stats["latest_grades_total"] == 0
    assert stats["average_latest"] is None
    assert stats["average_all"] is None
    assert stats["attendance"] == {
        "members_with_attendance": 0,
        "attended_classes": 0,
        "total_classes": 0,
        "attendance_percentage": None,
    }
    assert stats["comments"] == {
        "feedback_total": 0,
        "feedback_requested": 0,
        "feedback_corrected": 0,
        "annotations_total": 0,
    }
    assert stats["technologies_total"] == 0
    assert body["activity_statistics"] == []
    assert body["member_statistics"] == []
    assert body["technologies"] == []


async def test_complete_project_statistics(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    scores = await _scores(client, admin, ctx["sy"])

    first_class = await _class_with_session(ctx["sy"], date(2026, 3, 3))
    second_class = await _class_with_session(ctx["sy"], date(2026, 3, 10))
    await _mark(ctx["ana_cursada"].id_student_section_year, first_class)
    await _mark(ctx["ana_cursada"].id_student_section_year, second_class)
    await _mark(ctx["luis_cursada"].id_student_section_year, first_class)

    await _grade(
        client, admin, ctx["first_delivery"], "activity", scores["good"]["id_score"]
    )
    await _grade(
        client, admin, ctx["first_delivery"], "activity", scores["excellent"]["id_score"]
    )
    await _grade(
        client, admin, ctx["first_delivery"], "follow_up", scores["regular"]["id_score"]
    )
    await _grade(
        client, admin, ctx["second_delivery"], "activity", scores["very_good"]["id_score"]
    )
    await _action(client, admin, ctx["first_delivery"], "submit")
    await _action(client, admin, ctx["second_delivery"], "submit")
    await _action(client, admin, ctx["second_delivery"], "approve")

    feedback = (await _create_comment(client, admin, ctx["first_delivery"], "Revisar")).json()
    corrected = (await _create_comment(client, admin, ctx["first_delivery"], "Otra")).json()
    assert (
        await client.post(
            f"/delivery-comments/{corrected['id_delivery_comment']}/correct",
            headers=admin,
        )
    ).status_code == 200
    assert (
        await _create_comment(
            client, admin, ctx["first_delivery"], "Interna", "annotation"
        )
    ).status_code == 201
    assert feedback["status"]["code"] == "requested"

    await _add_technology(client, admin, ctx["project"]["id_project"], "FastAPI")
    await _add_technology(client, admin, ctx["project"]["id_project"], "React")

    body = (
        await _statistics(
            client, await login(ctx["mail"]), ctx["project"]["id_project"]
        )
    ).json()
    stats = body["statistics"]
    assert stats["activities_total"] == 2
    assert stats["deliveries_by_status"] == {
        "requested": 0,
        "pending_approval": 1,
        "pending_modification": 0,
        "approved": 1,
    }
    assert stats["members_by_status"] == {
        "active": 1,
        "finished": 1,
        "pending_approval": 1,
        "abandoned": 1,
        "expelled": 1,
        "rejected": 1,
    }
    assert stats["members_total"] == 6
    assert stats["grades_total"] == 4
    assert stats["latest_grades_total"] == 3
    assert stats["average_latest"] == 78.33
    assert stats["average_all"] == 75.0
    assert stats["average_latest_activity"] == 90.0
    assert stats["average_latest_follow_up"] == 55.0
    assert stats["attendance"] == {
        "members_with_attendance": 2,
        "attended_classes": 3,
        "total_classes": 4,
        "attendance_percentage": 75.0,
    }
    assert stats["comments"] == {
        "feedback_total": 2,
        "feedback_requested": 1,
        "feedback_corrected": 1,
        "annotations_total": 1,
    }
    assert stats["technologies_total"] == 2

    by_activity = {item["id_activity"]: item for item in body["activity_statistics"]}
    first = by_activity[ctx["first_activity"]["id_activity"]]
    second = by_activity[ctx["second_activity"]["id_activity"]]
    assert first["delivery_status"]["code"] == "pending_approval"
    assert first["grades_total"] == 3
    assert first["latest_activity"]["score"]["code"] == "excellent"
    assert first["latest_follow_up"]["score"]["code"] == "regular"
    assert first["average_latest"] == 77.5
    assert first["average_all"] == 73.33
    assert second["delivery_status"]["code"] == "approved"
    assert second["latest_activity"]["score"]["code"] == "very_good"
    assert [item["name"] for item in body["technologies"]] == ["FastAPI", "React"]
    assert body["member_statistics"][0]["attendance"] == {
        "attended_classes": 2,
        "total_classes": 2,
        "attendance_percentage": 100.0,
    }
    assert {item["status"]["code"] for item in body["member_statistics"]} == {
        "active",
        "finished",
    }
