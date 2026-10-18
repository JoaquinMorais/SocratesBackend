from config.database import SessionLocal
from models import Project, ProjectStatus
from tests.helpers import STUDENT, SUPER_ADMIN

LUIS = "100002@sistemas.frc.utn.edu.ar"
URL = "/projects"


# ---------- helpers ----------
async def _section_year(client, headers, name: str = "3K1", year: int = 2025) -> int:
    r = await client.post("/sections", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    r = await client.post(
        "/section-years",
        json={"year": year, "id_section": r.json()["id_section"], "min_students": 1, "max_students": 10},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id_section_year"]


async def _create(client, headers, id_section_year: int, **extra) -> dict:
    r = await client.post(URL, json={"id_section_year": id_section_year, **extra}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def _set_privacy(id_project: int, privacy: str) -> None:
    async with SessionLocal() as s:
        project = await s.get(Project, id_project)
        project.privacy = privacy
        s.add(project)
        await s.commit()


async def _add_history(id_project: int, from_code: str | None, to_code: str) -> None:
    async with SessionLocal() as s:
        from utils.statuses import get_status
        from_status = await get_status(s, "project", from_code) if from_code else None
        to_status = await get_status(s, "project", to_code)
        s.add(
            ProjectStatus(
                id_project=id_project,
                id_status_from=from_status.id_status if from_status else None,
                id_status_to=to_status.id_status,
            )
        )
        await s.commit()


# ---------- permisos ----------
async def test_requires_authentication(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    r = await client.get(f"{URL}/{p['id_project']}/status-history")
    assert r.status_code == 401


async def test_private_project_history_hidden_from_outsiders(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)  # private por defecto
    headers = await login(STUDENT)
    r = await client.get(f"{URL}/{p['id_project']}/status-history", headers=headers)
    assert r.status_code == 403


async def test_history_visible_for_public_project(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    await _set_privacy(p["id_project"], "public")
    headers = await login(STUDENT)
    r = await client.get(f"{URL}/{p['id_project']}/status-history", headers=headers)
    assert r.status_code == 200


# ---------- consultar ----------
async def test_history_has_initial_record_after_create(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    body = (await client.get(f"{URL}/{p['id_project']}/status-history", headers=admin)).json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["status_from"] is None
    assert item["status_to"]["code"] == "uninsured"
    assert item["status_to"]["ambito"] == "project"


async def test_history_returns_public_fields(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    body = (await client.get(f"{URL}/{p['id_project']}/status-history", headers=admin)).json()
    assert set(body["items"][0]) == {
        "id_project_status", "id_project", "status_from", "status_to", "changed_at",
    }


async def test_history_order_is_chronological(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    pid = p["id_project"]
    await _add_history(pid, "uninsured", "in_idea")
    await _add_history(pid, "in_idea", "in_progress")
    body = (await client.get(f"{URL}/{pid}/status-history", headers=admin)).json()
    codes = [(i["status_from"]["code"] if i["status_from"] else None, i["status_to"]["code"]) for i in body["items"]]
    assert codes == [
        (None, "uninsured"),
        ("uninsured", "in_idea"),
        ("in_idea", "in_progress"),
    ]


async def test_history_pagination(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    pid = p["id_project"]
    await _add_history(pid, "uninsured", "in_idea")
    await _add_history(pid, "in_idea", "in_progress")
    r = await client.get(f"{URL}/{pid}/status-history?limit=2", headers=admin)
    body = r.json()
    assert len(body["items"]) == 2 and body["total"] == 3
    r = await client.get(f"{URL}/{pid}/status-history?limit=2&offset=2", headers=admin)
    body = r.json()
    assert len(body["items"]) == 1
    r = await client.get(f"{URL}/{pid}/status-history?limit=0", headers=admin)
    assert r.status_code == 422


async def test_history_not_found(client, login):
    admin = await login(SUPER_ADMIN)
    r = await client.get(f"{URL}/99999/status-history", headers=admin)
    assert r.status_code == 404
