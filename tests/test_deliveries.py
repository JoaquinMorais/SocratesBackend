from datetime import date

from sqlmodel import select

from config.database import SessionLocal
from models import Delivery, Project, StudentProject
from tests.helpers import SUPER_ADMIN, assign_professor, section_year
from utils.statuses import get_status

PROJECTS = "/projects"
ACTIVITIES = "/activities"
ANA_ID = 1
LUIS_ID = 2
LUIS = "100002@sistemas.frc.utn.edu.ar"


async def _project(client, headers, id_section_year: int, quantity: int | None = None) -> dict:
    if quantity is not None:
        r = await client.post(
            f"{PROJECTS}/bulk",
            json={"id_section_year": id_section_year, "quantity": quantity},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        return r.json()
    r = await client.post(
        PROJECTS, json={"id_section_year": id_section_year}, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _activity(
    client,
    headers,
    id_section_year: int,
    title: str = "Entrega",
    *,
    link_required: bool = False,
) -> dict:
    r = await client.post(
        f"/section-years/{id_section_year}/activities",
        json={
            "title": title,
            "due_date": "2026-05-15",
            "due_time": "23:59",
            "link_required": link_required,
        },
        headers=headers,
    )
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


async def _set_status(id_project: int, code: str):
    async with SessionLocal() as session:
        project = await session.get(Project, id_project)
        project.id_status = (
            await get_status(session, "project", code)
        ).id_status
        session.add(project)
        await session.commit()


async def _project_deliveries(client, headers, id_project: int, **params):
    return await client.get(
        f"{PROJECTS}/{id_project}/deliveries", params=params, headers=headers
    )


async def _activity_deliveries(client, headers, id_activity: int, **params):
    return await client.get(
        f"{ACTIVITIES}/{id_activity}/deliveries", params=params, headers=headers
    )


async def _delivery_id(id_project: int, id_activity: int) -> int:
    async with SessionLocal() as session:
        return (
            await session.exec(
                select(Delivery.id_delivery).where(
                    Delivery.id_project == id_project,
                    Delivery.id_activity == id_activity,
                )
            )
        ).one()


async def _patch(client, headers, id_delivery: int, **body):
    return await client.patch(
        f"/deliveries/{id_delivery}", json=body, headers=headers
    )


async def _action(client, headers, id_delivery: int, action: str):
    return await client.post(
        f"/deliveries/{id_delivery}/{action}", headers=headers
    )


async def test_delivery_precreated_on_project_and_activity(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2026)
    first = await _project(client, admin, sy)
    activity = await _activity(client, admin, sy)

    body = (await _project_deliveries(client, admin, first["id_project"])).json()
    assert body["total"] == 1
    assert body["items"][0]["id_activity"] == activity["id_activity"]
    assert body["items"][0]["link"] is None
    assert body["items"][0]["activity_grade"] is None
    assert body["items"][0]["development_grade"] is None
    assert body["items"][0]["submitted_at"] is None
    assert body["items"][0]["updated_at"] is None
    assert body["items"][0]["status"]["code"] == "requested"

    second = await _project(client, admin, sy)
    body = (await _project_deliveries(client, admin, second["id_project"])).json()
    assert body["total"] == 1
    assert body["items"][0]["id_activity"] == activity["id_activity"]


async def test_delivery_precreated_when_activity_created_first(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2026)
    activity = await _activity(client, admin, sy)
    project = await _project(client, admin, sy)

    body = (await _project_deliveries(client, admin, project["id_project"])).json()
    assert body["total"] == 1
    delivery_id = body["items"][0]["id_delivery"]
    one = await client.get(f"/deliveries/{delivery_id}", headers=admin)
    assert one.status_code == 200
    assert one.json()["id_activity"] == activity["id_activity"]


async def test_delivery_precreated_on_bulk_projects(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2026)
    await _activity(client, admin, sy, "Primera")
    activities = await client.get(
        f"/section-years/{sy}/activities", headers=admin
    )
    assert activities.status_code == 200
    projects = await _project(client, admin, sy, quantity=2)

    async with SessionLocal() as session:
        rows = (await session.exec(select(Delivery))).all()
    assert len(rows) == 2 * len(activities.json()["items"])
    assert {row.id_project for row in rows} == {
        p["id_project"] for p in projects
    }


async def test_delivery_permissions(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2026)
    project = await _project(client, admin, sy)
    activity = await _activity(client, admin, sy)
    await _membership(project["id_project"], ANA_ID, "active", leader=True)
    delivery_id = await _delivery_id(project["id_project"], activity["id_activity"])

    ana = await login("100001@sistemas.frc.utn.edu.ar")
    luis = await login(LUIS)
    assert (await _project_deliveries(client, ana, project["id_project"])).status_code == 200
    assert (await _project_deliveries(client, luis, project["id_project"])).status_code == 403
    assert (await _activity_deliveries(client, ana, activity["id_activity"])).status_code == 403

    other = await make_professor("prof-del-otro@frc.utn.edu.ar")
    assigned = await make_professor("prof-del@frc.utn.edu.ar", legajo=300005)
    await assign_professor(client, admin, assigned, sy)
    assert (
        await _activity_deliveries(client, await login(other), activity["id_activity"])
    ).status_code == 403
    assert (
        await _activity_deliveries(client, await login(assigned), activity["id_activity"])
    ).status_code == 200
    assert (await _activity_deliveries(client, admin, activity["id_activity"])).status_code == 200

    # El alumno puede enviar el link, pero no cargar notas.
    r = await _patch(client, ana, delivery_id, link="https://drive.google.com/folder/1")
    assert r.status_code == 200, r.text
    assert r.json()["submitted_at"] is not None
    assert (
        await _patch(client, ana, delivery_id, activity_grade=80)
    ).status_code == 403

    # El profesor califica y puede modificar el link.
    r = await _patch(
        client,
        await login(assigned),
        delivery_id,
        activity_grade=80,
        development_grade=90,
    )
    assert r.status_code == 200, r.text
    assert r.json()["activity_grade"] == 80
    assert r.json()["development_grade"] == 90


async def test_delivery_fields_validation_and_timestamps(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2026)
    project = await _project(client, admin, sy)
    activity = await _activity(client, admin, sy)
    delivery_id = await _delivery_id(project["id_project"], activity["id_activity"])

    assert (await _patch(client, admin, delivery_id, activity_grade=0)).status_code == 422
    assert (await _patch(client, admin, delivery_id, activity_grade=101)).status_code == 422
    assert (await _patch(client, admin, delivery_id, link="not-a-url")).status_code == 422
    assert (await _patch(client, admin, delivery_id)).status_code == 422
    assert (
        await _patch(client, admin, delivery_id, extra="x")
    ).status_code == 422

    r = await _patch(client, admin, delivery_id, development_grade=75)
    assert r.status_code == 200
    first_updated = r.json()["updated_at"]
    assert r.json()["submitted_at"] is None

    r = await _patch(client, admin, delivery_id, link="https://example.com/drive")
    assert r.status_code == 200
    assert r.json()["submitted_at"] is not None
    second_updated = r.json()["updated_at"]
    assert second_updated >= first_updated

    r = await _patch(client, admin, delivery_id, link=None)
    assert r.status_code == 200
    assert r.json()["submitted_at"] is None
    assert r.json()["development_grade"] == 75


async def test_delivery_final_project_student_cannot_update(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2026)
    project = await _project(client, admin, sy)
    activity = await _activity(client, admin, sy)
    await _membership(project["id_project"], ANA_ID, "active", leader=True)
    await _set_status(project["id_project"], "approved")
    delivery_id = await _delivery_id(project["id_project"], activity["id_activity"])
    ana = await login("100001@sistemas.frc.utn.edu.ar")

    assert (
        await _patch(client, ana, delivery_id, link="https://example.com/final")
    ).status_code == 409
    assert (
        await _patch(
            client, admin, delivery_id, link="https://example.com/final", activity_grade=80
        )
    ).status_code == 200


async def test_delivery_repair_endpoint(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2026)
    project = await _project(client, admin, sy)
    activity = await _activity(client, admin, sy)
    delivery_id = await _delivery_id(project["id_project"], activity["id_activity"])

    r = await client.post(
        f"{PROJECTS}/{project['id_project']}/deliveries",
        json={"id_activity": activity["id_activity"], "link": "https://example.com/x"},
        headers=admin,
    )
    assert r.status_code == 409

    async with SessionLocal() as session:
        delivery = await session.get(Delivery, delivery_id)
        await session.delete(delivery)
        await session.commit()

    r = await client.post(
        f"{PROJECTS}/{project['id_project']}/deliveries",
        json={"id_activity": activity["id_activity"], "link": "https://example.com/x"},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    assert r.json()["submitted_at"] is not None

    other_sy = await section_year(client, admin, "3K2", 2026)
    other_activity = await _activity(client, admin, other_sy)
    r = await client.post(
        f"{PROJECTS}/{project['id_project']}/deliveries",
        json={"id_activity": other_activity["id_activity"], "link": "https://example.com/y"},
        headers=admin,
    )
    assert r.status_code == 422


async def test_delivery_deletion_rules(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2026)
    project = await _project(client, admin, sy)
    activity = await _activity(client, admin, sy)
    delivery_id = await _delivery_id(project["id_project"], activity["id_activity"])

    # Sin datos, la actividad y el proyecto se pueden borrar.
    assert (
        await client.delete(f"{ACTIVITIES}/{activity['id_activity']}", headers=admin)
    ).status_code == 204
    assert (
        await client.delete(f"{PROJECTS}/{project['id_project']}", headers=admin)
    ).status_code == 204

    project = await _project(client, admin, sy)
    activity = await _activity(client, admin, sy)
    delivery_id = await _delivery_id(project["id_project"], activity["id_activity"])
    assert (await _patch(client, admin, delivery_id, link="https://example.com/x")).status_code == 200

    assert (
        await client.delete(f"{ACTIVITIES}/{activity['id_activity']}", headers=admin)
    ).status_code == 409
    assert (
        await client.delete(f"{PROJECTS}/{project['id_project']}", headers=admin)
    ).status_code == 409
    assert (
        await client.delete(f"/section-years/{sy}", headers=admin)
    ).status_code == 409


async def test_delivery_precreated_from_calendar_bulk(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2026)
    project = await _project(client, admin, sy)
    r = await client.post(
        f"/section-years/{sy}/calendar/bulk",
        json={
            "classes": [],
            "activities": [
                {
                    "title": "Bulk",
                    "due_date": "2026-06-01",
                }
            ],
        },
        headers=admin,
    )
    assert r.status_code == 201, r.text
    body = (await _project_deliveries(client, admin, project["id_project"])).json()
    assert body["total"] == 1
    assert body["items"][0]["activity"]["title"] == "Bulk"


async def test_delivery_status_lifecycle(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2026)
    project = await _project(client, admin, sy)
    activity = await _activity(client, admin, sy)
    await _membership(project["id_project"], ANA_ID, "active", leader=True)
    delivery_id = await _delivery_id(project["id_project"], activity["id_activity"])
    ana = await login("100001@sistemas.frc.utn.edu.ar")

    r = await _patch(client, ana, delivery_id, link="https://example.com/one")
    assert r.status_code == 200
    assert r.json()["status"]["code"] == "requested"

    r = await _action(client, ana, delivery_id, "submit")
    assert r.status_code == 200, r.text
    assert r.json()["status"]["code"] == "pending_approval"

    assert (
        await _patch(client, ana, delivery_id, link="https://example.com/two")
    ).status_code == 409
    r = await _patch(client, admin, delivery_id, link="https://example.com/two")
    assert r.status_code == 200
    assert r.json()["status"]["code"] == "pending_approval"

    r = await _action(client, ana, delivery_id, "withdraw")
    assert r.status_code == 200
    assert r.json()["status"]["code"] == "requested"
    assert (
        await _patch(client, ana, delivery_id, link="https://example.com/three")
    ).status_code == 200

    assert (await _action(client, ana, delivery_id, "submit")).status_code == 200
    r = await _action(client, admin, delivery_id, "reject")
    assert r.status_code == 200
    assert r.json()["status"]["code"] == "pending_modification"
    assert (
        await _patch(client, ana, delivery_id, link="https://example.com/four")
    ).status_code == 200
    assert (await _action(client, ana, delivery_id, "submit")).status_code == 200
    r = await _action(client, admin, delivery_id, "approve")
    assert r.status_code == 200
    assert r.json()["status"]["code"] == "approved"

    assert (
        await _patch(client, ana, delivery_id, link="https://example.com/five")
    ).status_code == 409
    r = await _patch(client, admin, delivery_id, link="https://example.com/five")
    assert r.status_code == 200
    assert r.json()["status"]["code"] == "approved"


async def test_delivery_submit_requires_link_only_when_activity_requires_it(
    client, login
):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2026)
    project = await _project(client, admin, sy)
    required = await _activity(client, admin, sy, "Con link", link_required=True)
    optional = await _activity(client, admin, sy, "Sin link", link_required=False)
    await _membership(project["id_project"], ANA_ID, "active", leader=True)
    ana = await login("100001@sistemas.frc.utn.edu.ar")

    required_id = await _delivery_id(project["id_project"], required["id_activity"])
    optional_id = await _delivery_id(project["id_project"], optional["id_activity"])
    assert (await _action(client, ana, required_id, "submit")).status_code == 409
    assert (await _action(client, ana, optional_id, "submit")).status_code == 200

    assert (
        await _patch(client, ana, required_id, link="https://example.com/required")
    ).status_code == 200
    assert (await _action(client, ana, required_id, "submit")).status_code == 200


async def test_delivery_actions_permissions(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2026)
    project = await _project(client, admin, sy)
    activity = await _activity(client, admin, sy)
    await _membership(project["id_project"], ANA_ID, "active", leader=True)
    delivery_id = await _delivery_id(project["id_project"], activity["id_activity"])
    ana = await login("100001@sistemas.frc.utn.edu.ar")
    luis = await login(LUIS)

    assert (await _action(client, luis, delivery_id, "submit")).status_code == 403
    assert (await _action(client, luis, delivery_id, "withdraw")).status_code == 403
    assert (await _action(client, luis, delivery_id, "approve")).status_code == 403
    assert (await _action(client, luis, delivery_id, "reject")).status_code == 403

    await _action(client, ana, delivery_id, "submit")
    assert (await _action(client, luis, delivery_id, "approve")).status_code == 403
    assert (await _action(client, luis, delivery_id, "reject")).status_code == 403
