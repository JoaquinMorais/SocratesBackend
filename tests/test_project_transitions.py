from sqlmodel import select

from config.database import SessionLocal
from models import Project, StudentProject, StudentSectionYear
from tests.helpers import STUDENT, SUPER_ADMIN
from utils.statuses import get_status

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


async def _transition(client, headers, id_project: int, action: str):
    return await client.post(f"{URL}/{id_project}/{action}", headers=headers)


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


async def _set_project_status(id_project: int, code: str) -> None:
    async with SessionLocal() as s:
        status = await get_status(s, "project", code)
        project = await s.get(Project, id_project)
        project.id_status = status.id_status
        s.add(project)
        await s.commit()


async def _get_memory(id_project: int) -> int | None:
    async with SessionLocal() as s:
        project = await s.get(Project, id_project)
        return project.id_status_insured


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
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    await _set_project_status(p["id_project"], "in_idea")
    for action in ("uninsure", "start", "submit", "approve", "reject", "retry", "cancel"):
        r = await client.post(f"{URL}/{p['id_project']}/{action}")
        assert r.status_code == 401, action


async def test_student_cannot_change_status(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    await _set_project_status(p["id_project"], "in_idea")
    headers = await login(STUDENT)
    for action in ("uninsure", "start", "submit", "approve", "reject", "retry", "cancel"):
        r = await _transition(client, headers, p["id_project"], action)
        assert r.status_code == 403, action


async def test_group_leader_cannot_change_status(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    await _set_project_status(p["id_project"], "in_idea")
    headers = await login(STUDENT)  # Ana es la jefa
    for action in ("uninsure", "start", "submit", "approve", "reject", "retry", "cancel"):
        r = await _transition(client, headers, p["id_project"], action)
        assert r.status_code == 403, action


async def test_unassigned_professor_cannot_change_status(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    await _set_project_status(p["id_project"], "in_idea")
    headers = await login(await make_professor("prof@frc.utn.edu.ar"))
    for action in ("uninsure", "start", "submit", "approve", "reject", "retry", "cancel"):
        r = await _transition(client, headers, p["id_project"], action)
        assert r.status_code == 403, action


async def test_assigned_professor_can_change_status(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    await _set_project_status(p["id_project"], "in_idea")
    mail = await make_professor("prof@frc.utn.edu.ar")
    await _assign_professor(client, admin, mail, sy)
    headers = await login(mail)
    assert (await _transition(client, headers, p["id_project"], "start")).status_code == 200


async def test_super_admin_can_change_status(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    await _set_project_status(p["id_project"], "in_idea")
    assert (await _transition(client, admin, p["id_project"], "start")).status_code == 200


async def test_unknown_project(client, login):
    admin = await login(SUPER_ADMIN)
    for action in ("uninsure", "start", "submit", "approve", "reject", "retry", "cancel"):
        r = await _transition(client, admin, 999, action)
        assert r.status_code == 404, action


# ---------- transiciones ----------
async def test_uninsure_from_each_insured_status(client, login):
    admin = await login(SUPER_ADMIN)
    for index, code in enumerate(("in_idea", "in_progress", "pending_approval", "rejected"), 1):
        sy = await _section_year(client, admin, name=f"U{index}K", year=2025)
        p = await _create(client, admin, sy)
        await _set_project_status(p["id_project"], code)
        r = await _transition(client, admin, p["id_project"], "uninsure")
        assert r.status_code == 200, code
        assert r.json()["status"]["code"] == "uninsured"
        assert r.json()["privacy"] == "public"  # efectiva: uninsured se trata como público


async def test_uninsure_writes_memory(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    await _set_project_status(p["id_project"], "in_progress")
    assert (await _transition(client, admin, p["id_project"], "uninsure")).status_code == 200
    memory = await _get_memory(p["id_project"])
    assert memory is not None  # guardó el subestado saliente (in_progress)


async def test_uninsure_then_insure_returns_to_same_substate(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    # asegurar → in_idea, avanzar a in_progress, desasegurar, volver a asegurar
    assert (await client.post(f"{URL}/{p['id_project']}/insure", headers=admin)).status_code == 200
    assert (await _transition(client, admin, p["id_project"], "start")).status_code == 200
    assert (await _transition(client, admin, p["id_project"], "uninsure")).status_code == 200
    r = await client.post(f"{URL}/{p['id_project']}/insure", headers=admin)
    assert r.status_code == 200
    assert r.json()["status"]["code"] == "in_progress"  # retomó el subestado


async def test_cannot_uninsure_from_uninsured(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)  # nace uninsured
    assert (await _transition(client, admin, p["id_project"], "uninsure")).status_code == 409


async def test_start_moves_idea_to_progress(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    await _set_project_status(p["id_project"], "in_idea")
    r = await _transition(client, admin, p["id_project"], "start")
    assert r.status_code == 200 and r.json()["status"]["code"] == "in_progress"


async def test_submit_moves_progress_to_pending(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    await _set_project_status(p["id_project"], "in_progress")
    r = await _transition(client, admin, p["id_project"], "submit")
    assert r.status_code == 200 and r.json()["status"]["code"] == "pending_approval"


async def test_approve_moves_pending_to_approved(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    await _set_project_status(p["id_project"], "pending_approval")
    r = await _transition(client, admin, p["id_project"], "approve")
    assert r.status_code == 200 and r.json()["status"]["code"] == "approved"


async def test_reject_moves_pending_to_rejected(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    await _set_project_status(p["id_project"], "pending_approval")
    r = await _transition(client, admin, p["id_project"], "reject")
    assert r.status_code == 200 and r.json()["status"]["code"] == "rejected"


async def test_retry_moves_rejected_to_progress(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    await _set_project_status(p["id_project"], "rejected")
    r = await _transition(client, admin, p["id_project"], "retry")
    assert r.status_code == 200 and r.json()["status"]["code"] == "in_progress"


async def test_cancel_from_uninsured(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)  # uninsured
    r = await _transition(client, admin, p["id_project"], "cancel")
    assert r.status_code == 200 and r.json()["status"]["code"] == "cancelled"


async def test_cancel_from_each_insured_status(client, login):
    admin = await login(SUPER_ADMIN)
    for index, code in enumerate(("in_idea", "in_progress", "pending_approval", "rejected"), 1):
        sy = await _section_year(client, admin, name=f"C{index}K", year=2025)
        p = await _create(client, admin, sy)
        await _set_project_status(p["id_project"], code)
        r = await _transition(client, admin, p["id_project"], "cancel")
        assert r.status_code == 200, code
        assert r.json()["status"]["code"] == "cancelled"


# ---------- transiciones no permitidas ----------
async def test_transition_not_allowed(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    await _set_project_status(p["id_project"], "in_idea")
    # start desde in_idea está bien; pero submit no
    r = await _transition(client, admin, p["id_project"], "submit")
    assert r.status_code == 409


async def test_cannot_cancel_final_project(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    await _set_project_status(p["id_project"], "approved")
    assert (await _transition(client, admin, p["id_project"], "cancel")).status_code == 409


async def test_cannot_change_status_of_final_project(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    await _set_project_status(p["id_project"], "cancelled")
    for action in ("uninsure", "start", "submit", "approve", "reject", "retry", "cancel"):
        r = await _transition(client, admin, p["id_project"], action)
        assert r.status_code == 409, action


# ---------- efectos en membresías ----------
async def test_cancel_abandons_active_members(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    await _add_membership(p["id_project"], LUIS_ID, "active")
    assert (await _transition(client, admin, p["id_project"], "cancel")).status_code == 200
    body = (
        await client.get(
            f"{URL}/{p['id_project']}/members", params={"status": "abandoned"}, headers=admin
        )
    ).json()
    assert {m["id_student"] for m in body["items"]} == {ANA_ID, LUIS_ID}


async def test_cancel_rejects_pending_requests(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    await _add_membership(p["id_project"], LUIS_ID, "pending_approval")
    assert (await _transition(client, admin, p["id_project"], "cancel")).status_code == 200
    body = (
        await client.get(
            f"{URL}/{p['id_project']}/members", params={"status": "rejected"}, headers=admin
        )
    ).json()
    assert [m["id_student"] for m in body["items"]] == [LUIS_ID]


async def test_approve_finishes_active_members(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    await _set_project_status(p["id_project"], "pending_approval")
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    await _add_membership(p["id_project"], LUIS_ID, "active")
    assert (await _transition(client, admin, p["id_project"], "approve")).status_code == 200
    body = (
        await client.get(
            f"{URL}/{p['id_project']}/members", params={"status": "finished"}, headers=admin
        )
    ).json()
    assert {m["id_student"] for m in body["items"]} == {ANA_ID, LUIS_ID}


# ---------- historial y ciclo ----------
async def test_history_records_each_transition(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    await client.post(f"{URL}/{p['id_project']}/insure", headers=admin)  # uninsured → in_idea
    await _transition(client, admin, p["id_project"], "start")  # → in_progress
    await _transition(client, admin, p["id_project"], "submit")  # → pending_approval
    await _transition(client, admin, p["id_project"], "approve")  # → approved
    body = (await client.get(f"{URL}/{p['id_project']}/status-history", headers=admin)).json()
    codes = [i["status_to"]["code"] for i in body["items"]]
    assert codes == ["uninsured", "in_idea", "in_progress", "pending_approval", "approved"]


async def test_full_rejection_cycle(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p = await _create(client, admin, sy)
    await _add_membership(p["id_project"], ANA_ID, "active", is_leader=True)
    await client.post(f"{URL}/{p['id_project']}/insure", headers=admin)
    await _transition(client, admin, p["id_project"], "start")
    await _transition(client, admin, p["id_project"], "submit")
    r = await _transition(client, admin, p["id_project"], "reject")
    assert r.json()["status"]["code"] == "rejected"
    r = await _transition(client, admin, p["id_project"], "retry")
    assert r.json()["status"]["code"] == "in_progress"
    # el grupo sigue asegurado, se puede enviar de nuevo
    assert (await _transition(client, admin, p["id_project"], "submit")).status_code == 200


# ---------- efectos en la cursada ----------
async def _cursada(id_student: int, id_section_year: int):
    async with SessionLocal() as s:
        return (
            await s.exec(
                select(StudentSectionYear).where(
                    StudentSectionYear.id_student == id_student,
                    StudentSectionYear.id_section_year == id_section_year,
                    StudentSectionYear.state != "registered",
                )
            )
        ).first()


async def test_approve_finishes_cursada(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    project = await _create(client, admin, sy)
    r = await client.post(
        f"{URL}/{project['id_project']}/members", headers=await login(STUDENT)
    )
    assert r.status_code == 201, r.text
    await _set_project_status(project["id_project"], "pending_approval")

    r = await _transition(client, admin, project["id_project"], "approve")
    assert r.status_code == 200, r.text
    row = await _cursada(ANA_ID, sy)
    assert row is not None and row.state == "finished_approved"


async def test_cancel_marks_cursada_finished_failed(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    project = await _create(client, admin, sy)
    r = await client.post(
        f"{URL}/{project['id_project']}/members", headers=await login(STUDENT)
    )
    assert r.status_code == 201, r.text

    r = await _transition(client, admin, project["id_project"], "cancel")
    assert r.status_code == 200, r.text
    row = await _cursada(ANA_ID, sy)
    assert row is not None and row.state == "finished_failed"
