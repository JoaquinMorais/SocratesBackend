from datetime import date

from config.database import SessionLocal
from models import Project, Student, StudentProject, User
from tests.helpers import PASSWORD, STUDENT, SUPER_ADMIN
from utils.statuses import get_status

LUIS = "100002@sistemas.frc.utn.edu.ar"
ANA_ID, LUIS_ID = 1, 2
URL = "/projects"


# ---------- helpers ----------
async def _section_year(
    client, headers, name: str = "3K1", year: int = 2025, min_students: int = 1, max_students: int = 10
) -> int:
    r = await client.post("/sections", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    r = await client.post(
        "/section-years",
        json={
            "year": year,
            "id_section": r.json()["id_section"],
            "min_students": min_students,
            "max_students": max_students,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id_section_year"]


async def _create(client, headers, id_section_year: int) -> dict:
    r = await client.post(URL, json={"id_section_year": id_section_year}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def _insure(client, headers, id_project: int):
    return await client.post(f"{URL}/{id_project}/insure", headers=headers)


async def _patch(client, admin, id_project: int, **fields) -> None:
    r = await client.patch(f"{URL}/{id_project}", json=fields, headers=admin)
    assert r.status_code == 200, r.text


async def _add_membership(
    id_project: int, id_student: int, code: str = "active", is_leader: bool = False
) -> int:
    async with SessionLocal() as s:
        status = await get_status(s, "student_project", code)
        membership = StudentProject(
            id_student=id_student,
            id_project=id_project,
            id_status=status.id_status,
            is_leader=is_leader,
        )
        s.add(membership)
        await s.commit()
        return membership.id_student_project


async def _make_student(legajo: int = 900001) -> int:
    async with SessionLocal() as s:
        user = User(
            first_name="Nuevo", last_name="Alumno", legajo=legajo, birth_date=date(2003, 1, 1)
        )
        user.set_password(PASSWORD)
        s.add(user)
        await s.flush()
        s.add(Student(id_student=user.id_user, enrollment_year=2021))
        await s.commit()
        return user.id_user


async def _set_project_status(id_project: int, code: str) -> None:
    async with SessionLocal() as s:
        status = await get_status(s, "project", code)
        project = await s.get(Project, id_project)
        project.id_status = status.id_status
        s.add(project)
        await s.commit()


async def _set_insured_memory(id_project: int, code: str | None) -> None:
    async with SessionLocal() as s:
        project = await s.get(Project, id_project)
        if code is None:
            project.id_status_insured = None
        else:
            status = await get_status(s, "project", code)
            project.id_status_insured = status.id_status
        s.add(project)
        await s.commit()


async def _prof_id(client, headers, mail: str) -> int:
    r = await client.get("/users", params={"q": mail}, headers=headers)
    return r.json()["items"][0]["id_user"]


async def _assign_professor(client, admin, mail: str, id_section_year: int) -> None:
    r = await client.post(
        "/professor-section-years",
        json={"id_professor": await _prof_id(client, admin, mail), "id_section_year": id_section_year},
        headers=admin,
    )
    assert r.status_code == 201, r.text


# ---------- permisos ----------
async def test_requires_authentication(client, login):
    admin = await login(SUPER_ADMIN)
    p = await _create(client, admin, await _section_year(client, admin))
    r = await client.post(f"{URL}/{p['id_project']}/insure")
    assert r.status_code == 401


async def test_leader_can_insure(client, login):
    admin = await login(SUPER_ADMIN)
    p = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    r = await _insure(client, await login(STUDENT), p["id_project"])
    assert r.status_code == 200 and r.json()["status"]["code"] == "in_idea"


async def test_assigned_professor_can_insure(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    mail = await make_professor("prof@frc.utn.edu.ar")
    await _assign_professor(client, admin, mail, sy)
    r = await _insure(client, await login(mail), p["id_project"])
    assert r.status_code == 200


async def test_super_admin_can_insure(client, login):
    admin = await login(SUPER_ADMIN)
    p = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    assert (await _insure(client, admin, p["id_project"])).status_code == 200


async def test_non_member_student_cannot_insure(client, login):
    admin = await login(SUPER_ADMIN)
    p = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    assert (await _insure(client, await login(LUIS), p["id_project"])).status_code == 403


async def test_non_leader_active_member_cannot_insure(client, login):
    admin = await login(SUPER_ADMIN)
    p = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    await _add_membership(p["id_project"], LUIS_ID, "active")
    assert (await _insure(client, await login(LUIS), p["id_project"])).status_code == 403


async def test_unassigned_professor_cannot_insure(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    p = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    headers = await login(await make_professor("prof@frc.utn.edu.ar"))
    assert (await _insure(client, headers, p["id_project"])).status_code == 403


async def test_pending_member_cannot_insure(client, login):
    admin = await login(SUPER_ADMIN)
    p = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    await _add_membership(p["id_project"], LUIS_ID, "pending_approval")
    assert (await _insure(client, await login(LUIS), p["id_project"])).status_code == 403


# ---------- reglas ----------
async def test_insure_moves_to_in_idea_by_default(client, login):
    admin = await login(SUPER_ADMIN)
    p = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    body = (await _insure(client, admin, p["id_project"])).json()
    assert body["status"]["code"] == "in_idea"
    assert body["status"]["is_insured"] is True


async def test_cannot_insure_already_insured(client, login):
    admin = await login(SUPER_ADMIN)
    p = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    await _set_project_status(p["id_project"], "in_progress")
    assert (await _insure(client, admin, p["id_project"])).status_code == 409


async def test_cannot_insure_final_project(client, login):
    admin = await login(SUPER_ADMIN)
    p = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    await _set_project_status(p["id_project"], "approved")
    assert (await _insure(client, admin, p["id_project"])).status_code == 409


async def test_insure_unknown_project(client, login):
    assert (await _insure(client, await login(SUPER_ADMIN), 999)).status_code == 404


async def test_insure_requires_min_students(client, login):
    admin = await login(SUPER_ADMIN)
    p = await _create(client, admin, await _section_year(client, admin, min_students=3, max_students=10))
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    await _add_membership(p["id_project"], LUIS_ID, "active")
    assert (await _insure(client, admin, p["id_project"])).status_code == 409


async def test_insure_with_exactly_min_students(client, login):
    admin = await login(SUPER_ADMIN)
    p = await _create(client, admin, await _section_year(client, admin, min_students=3, max_students=10))
    extra = await _make_student(900001)
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    await _add_membership(p["id_project"], LUIS_ID, "active")
    await _add_membership(p["id_project"], extra, "active")
    assert (await _insure(client, admin, p["id_project"])).status_code == 200


async def test_insure_rejects_more_than_max_students(client, login):
    admin = await login(SUPER_ADMIN)
    p = await _create(client, admin, await _section_year(client, admin, min_students=1, max_students=2))
    extra = await _make_student(900002)
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    await _add_membership(p["id_project"], LUIS_ID, "active")
    await _add_membership(p["id_project"], extra, "active")
    assert (await _insure(client, admin, p["id_project"])).status_code == 409


# ---------- efectos ----------
async def test_insure_records_history(client, login):
    admin = await login(SUPER_ADMIN)
    p = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    assert (await _insure(client, admin, p["id_project"])).status_code == 200
    body = (await client.get(f"{URL}/{p['id_project']}/status-history", headers=admin)).json()
    last = body["items"][-1]
    assert last["status_from"]["code"] == "uninsured"
    assert last["status_to"]["code"] == "in_idea"


async def test_cannot_join_after_insure(client, login):
    admin = await login(SUPER_ADMIN)
    p = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    assert (await _insure(client, admin, p["id_project"])).status_code == 200
    r = await client.post(f"{URL}/{p['id_project']}/members", headers=await login(LUIS))
    assert r.status_code == 409


async def test_insure_rejects_pending_requests(client, login):
    admin = await login(SUPER_ADMIN)
    p = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    await _add_membership(p["id_project"], LUIS_ID, "pending_approval")
    assert (await _insure(client, admin, p["id_project"])).status_code == 200
    body = (
        await client.get(
            f"{URL}/{p['id_project']}/members", params={"status": "rejected"}, headers=admin
        )
    ).json()
    assert [m["id_student"] for m in body["items"]] == [LUIS_ID]
    active = (
        await client.get(
            f"{URL}/{p['id_project']}/members", params={"status": "active"}, headers=admin
        )
    ).json()
    assert [m["id_student"] for m in active["items"]] == [ANA_ID]


async def test_insure_makes_private_privacy_apply(client, login):
    admin = await login(SUPER_ADMIN)
    p = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    await _patch(client, admin, p["id_project"], privacy="private")
    luis = await login(LUIS)
    assert (await client.get(f"{URL}/{p['id_project']}", headers=luis)).status_code == 200
    body = (await _insure(client, admin, p["id_project"])).json()
    assert body["privacy"] == "private"
    assert (await client.get(f"{URL}/{p['id_project']}", headers=luis)).status_code == 403


# ---------- memoria del subestado ----------
async def test_insure_defaults_to_in_idea_without_memory(client, login):
    admin = await login(SUPER_ADMIN)
    p = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    await _set_insured_memory(p["id_project"], None)
    assert (await _insure(client, admin, p["id_project"])).json()["status"]["code"] == "in_idea"


async def test_insure_returns_to_remembered_status(client, login):
    admin = await login(SUPER_ADMIN)
    p = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    await _set_insured_memory(p["id_project"], "in_progress")
    body = (await _insure(client, admin, p["id_project"])).json()
    assert body["status"]["code"] == "in_progress"
    history = (await client.get(f"{URL}/{p['id_project']}/status-history", headers=admin)).json()
    assert history["items"][-1]["status_to"]["code"] == "in_progress"
