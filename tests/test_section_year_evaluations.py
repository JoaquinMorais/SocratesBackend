from sqlmodel import select

from config.database import SessionLocal
from models import StudentProject
from tests.helpers import (
    STUDENT,
    SUPER_ADMIN,
    assign_professor,
    section_year,
)
from utils.statuses import get_status

URL = "/section-years"
ANA_ID = 1
ANA = "100001@sistemas.frc.utn.edu.ar"


async def _membership(id_project: int, id_student: int, code: str = "active"):
    async with SessionLocal() as session:
        membership_status = await get_status(session, "student_project", code)
        session.add(
            StudentProject(
                id_project=id_project,
                id_student=id_student,
                id_status=membership_status.id_status,
                is_leader=True,
            )
        )
        await session.commit()


async def _project(client, admin, id_section_year: int) -> dict:
    r = await client.post(
        "/projects", json={"id_section_year": id_section_year}, headers=admin
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _activity(client, admin, id_section_year: int) -> dict:
    r = await client.post(
        f"/section-years/{id_section_year}/activities",
        json={"title": "Entrega", "due_date": "2026-05-15"},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _delivery_id(client, admin, id_project: int, id_activity: int) -> int:
    body = (
        await client.get(f"/projects/{id_project}/deliveries", headers=admin)
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


async def _grade(client, admin, id_delivery: int, id_score: int):
    return await client.post(
        f"/deliveries/{id_delivery}/grades",
        json={"category": "activity", "id_score": id_score},
        headers=admin,
    )


async def _setup(client, admin, make_professor, *, assigned: bool = True):
    sy = await section_year(client, admin, "3K1", 2026)
    first = await _project(client, admin, sy)
    second = await _project(client, admin, sy)
    activity = await _activity(client, admin, sy)
    await _membership(first["id_project"], ANA_ID)
    mail = await make_professor("prof-section-eval@frc.utn.edu.ar")
    if assigned:
        await assign_professor(client, admin, mail, sy)
    return {
        "sy": sy,
        "first": first,
        "second": second,
        "activity": activity,
        "first_delivery": await _delivery_id(
            client, admin, first["id_project"], activity["id_activity"]
        ),
        "second_delivery": await _delivery_id(
            client, admin, second["id_project"], activity["id_activity"]
        ),
        "mail": mail,
    }


async def _evaluations(client, headers, id_section_year: int):
    return await client.get(
        f"{URL}/{id_section_year}/evaluations", headers=headers
    )


# ---------- permisos ----------
async def test_requires_authentication(client):
    assert (await client.get(f"{URL}/1/evaluations")).status_code == 401


async def test_student_and_unassigned_professor_forbidden(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor, assigned=False)
    assert (
        await _evaluations(client, await login(ANA), ctx["sy"])
    ).status_code == 403
    assert (
        await _evaluations(client, await login(ctx["mail"]), ctx["sy"])
    ).status_code == 403


async def test_assigned_professor_and_super_admin_can_read(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    assert (
        await _evaluations(client, await login(ctx["mail"]), ctx["sy"])
    ).status_code == 200
    assert (await _evaluations(client, admin, ctx["sy"])).status_code == 200


async def test_unknown_section_year(client, login):
    assert (
        await _evaluations(client, await login(SUPER_ADMIN), 999999)
    ).status_code == 404


# ---------- contenido ----------
async def test_section_year_evaluations_include_all_projects(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    scores = await _scores(client, admin, ctx["sy"])
    assert (
        await _grade(
            client,
            admin,
            ctx["first_delivery"],
            scores["excellent"]["id_score"],
        )
    ).status_code == 201

    body = (await _evaluations(client, admin, ctx["sy"])).json()
    assert body["section_year"]["id_section_year"] == ctx["sy"]
    assert [item["project"]["group_number"] for item in body["projects"]] == [1, 2]
    assert [item["project"]["id_project"] for item in body["projects"]] == [
        ctx["first"]["id_project"],
        ctx["second"]["id_project"],
    ]

    first, second = body["projects"]
    assert first["statistics"]["grades_total"] == 1
    assert first["statistics"]["average_latest"] == 100.0
    assert len(first["activities"]) == 1
    assert first["members"][0]["id_student"] == ANA_ID
    assert second["statistics"]["grades_total"] == 0
    assert second["statistics"]["average_latest"] is None
    assert second["statistics"]["members_total"] == 0
    assert second["activities"][0]["grades"] == []


async def test_section_year_without_projects(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2026)
    body = (await _evaluations(client, admin, sy)).json()
    assert body["section_year"]["id_section_year"] == sy
    assert body["projects"] == []
