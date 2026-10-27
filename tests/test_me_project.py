from datetime import datetime, timezone

from config.database import SessionLocal
from models import Project, StudentProject
from tests.helpers import STUDENT, SUPER_ADMIN
from utils.statuses import get_status

LUIS = "100002@sistemas.frc.utn.edu.ar"
ANA_ID, LUIS_ID = 1, 2
T1 = datetime(2025, 3, 1, tzinfo=timezone.utc)
T2 = datetime(2025, 3, 2, tzinfo=timezone.utc)


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


async def _create(client, headers, id_section_year: int) -> dict:
    r = await client.post("/projects", json={"id_section_year": id_section_year}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def _create_with_leader(client, admin, name: str) -> dict:
    """Un grupo vacío cuya jefatura ya la tiene Ana (para que las solicitudes
    de Luis queden `pending_approval`)."""
    project = await _create(client, admin, await _section_year(client, admin, name=name))
    await _add_membership(project["id_project"], ANA_ID, "active", is_leader=True)
    return project


async def _join(client, headers, id_project: int):
    return await client.post(f"/projects/{id_project}/members", headers=headers)


async def _add_membership(
    id_project: int,
    id_student: int,
    code: str = "active",
    is_leader: bool = False,
    enrolled_at: datetime | None = None,
) -> int:
    async with SessionLocal() as s:
        status = await get_status(s, "student_project", code)
        extra = {"enrolled_at": enrolled_at} if enrolled_at is not None else {}
        membership = StudentProject(
            id_student=id_student,
            id_project=id_project,
            id_status=status.id_status,
            is_leader=is_leader,
            **extra,
        )
        s.add(membership)
        await s.commit()
        return membership.id_student_project


async def _set_membership_status(id_student_project: int, code: str) -> None:
    async with SessionLocal() as s:
        status = await get_status(s, "student_project", code)
        membership = await s.get(StudentProject, id_student_project)
        membership.id_status = status.id_status
        s.add(membership)
        await s.commit()


async def _set_project_status(id_project: int, code: str) -> None:
    async with SessionLocal() as s:
        status = await get_status(s, "project", code)
        project = await s.get(Project, id_project)
        project.id_status = status.id_status
        s.add(project)
        await s.commit()


async def _patch_project(client, admin, id_project: int, **fields) -> None:
    r = await client.patch(f"/projects/{id_project}", json=fields, headers=admin)
    assert r.status_code == 200, r.text


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
async def test_requires_authentication(client):
    assert (await client.get("/me/project")).status_code == 401


async def test_professor_and_super_admin_forbidden(client, login, make_professor):
    for mail in (SUPER_ADMIN, await make_professor("prof@frc.utn.edu.ar")):
        r = await client.get("/me/project", headers=await login(mail))
        assert r.status_code == 403, (mail, r.text)


# ---------- consultar ----------
async def test_no_team_and_no_requests(client, login):
    body = (await client.get("/me/project", headers=await login(STUDENT))).json()
    assert body == {"project": None, "requests": []}


async def test_team_with_leader_responsible_and_overview_fields(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    ana_headers = await login(STUDENT)
    r = await _join(client, ana_headers, project["id_project"])
    assert r.status_code == 201, r.text  # Ana entra como jefe (grupo vacío)
    prof_mail = await make_professor("prof-own@frc.utn.edu.ar")
    await _assign_professor(client, admin, prof_mail, project["id_section_year"])
    prof_id = await _prof_id(client, admin, prof_mail)

    body = (await client.get("/me/project", headers=ana_headers)).json()
    p = body["project"]
    assert p["id_project"] == project["id_project"]
    assert p["status"]["code"] == "uninsured" and p["privacy"] == "public"
    assert p["restricted"] is False and p["name"] is None
    assert [m["id_student"] for m in p["members"]] == [ANA_ID]
    assert p["leader"]["id_student"] == ANA_ID and p["leader"]["is_leader"] is True
    assert [resp["id_professor"] for resp in p["responsible"]] == [prof_id]
    assert body["requests"] == []


async def test_member_data_has_no_private_fields(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(project["id_project"], ANA_ID, "active", is_leader=True)

    body = (await client.get("/me/project", headers=await login(STUDENT))).json()
    first = body["project"]["members"][0]
    assert "email" not in first and "birth_date" not in first
    assert "id_student_project" in first and "enrolled_at" in first and "status" in first


async def test_finished_membership_is_still_the_team(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    id_sp = await _add_membership(project["id_project"], ANA_ID, "active", is_leader=True)
    await _set_membership_status(id_sp, "finished")
    await _set_project_status(project["id_project"], "approved")

    body = (await client.get("/me/project", headers=await login(STUDENT))).json()
    assert body["project"]["id_project"] == project["id_project"]
    assert body["project"]["status"]["code"] == "approved"  # estado final
    assert [m["status"]["code"] for m in body["project"]["members"]] == ["finished"]
    assert body["project"]["leader"]["id_student"] == ANA_ID  # conserva la jefatura
    assert body["requests"] == []


async def test_private_team_seen_in_full_by_its_member(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(project["id_project"], ANA_ID, "active", is_leader=True)
    await _patch_project(client, admin, project["id_project"], privacy="private", name="Secreto")
    await _set_project_status(project["id_project"], "in_idea")

    body = (await client.get("/me/project", headers=await login(STUDENT))).json()
    p = body["project"]
    assert p["privacy"] == "private" and p["name"] == "Secreto"
    assert p["restricted"] is False  # el miembro ve todo


async def test_pending_request_with_no_team(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create_with_leader(client, admin, "3K2")
    r = await _join(client, await login(LUIS), project["id_project"])
    assert r.status_code == 201, r.text  # queda pending_approval

    body = (await client.get("/me/project", headers=await login(LUIS))).json()
    assert body["project"] is None
    assert len(body["requests"]) == 1
    req = body["requests"][0]
    assert req["id_project"] == project["id_project"]
    assert req["group_number"] == project["group_number"]
    assert req["section_name"] == "3K2" and req["year"] == 2025
    assert req["id_section_year"] == project["id_section_year"]
    assert req["status"]["code"] == "pending_approval"
    assert req["is_leader"] is False


async def test_rejected_request_while_member_of_another_project(client, login):
    admin = await login(SUPER_ADMIN)
    rejected_in = await _create(client, admin, await _section_year(client, admin))
    id_sp = await _add_membership(rejected_in["id_project"], ANA_ID, "pending_approval")
    await _set_membership_status(id_sp, "rejected")

    team = await _create(client, admin, await _section_year(client, admin, name="3K3"))
    await _add_membership(team["id_project"], ANA_ID, "active", is_leader=True)

    body = (await client.get("/me/project", headers=await login(STUDENT))).json()
    assert body["project"]["id_project"] == team["id_project"]
    assert [rq["id_project"] for rq in body["requests"]] == [rejected_in["id_project"]]
    assert body["requests"][0]["status"]["code"] == "rejected"  # se ve aunque haya equipo


async def test_requests_ordered_pending_first_then_by_newest(client, login):
    admin = await login(SUPER_ADMIN)
    rejected_old = await _create_with_leader(client, admin, "3K4")  # solicitada en T1
    rejected_new = await _create_with_leader(client, admin, "3K5")  # solicitada en T2
    pending_project = await _create_with_leader(client, admin, "3K6")

    id_old = await _add_membership(rejected_old["id_project"], LUIS_ID, "pending_approval", enrolled_at=T1)
    id_new = await _add_membership(rejected_new["id_project"], LUIS_ID, "pending_approval", enrolled_at=T2)
    await _add_membership(pending_project["id_project"], LUIS_ID, "pending_approval", enrolled_at=T1)
    await _set_membership_status(id_old, "rejected")
    await _set_membership_status(id_new, "rejected")

    body = (await client.get("/me/project", headers=await login(LUIS))).json()
    assert body["project"] is None
    assert [rq["id_project"] for rq in body["requests"]] == [
        pending_project["id_project"],  # pendiente primero
        rejected_new["id_project"],     # rechazadas, de la más nueva a la más vieja
        rejected_old["id_project"],
    ]


async def test_abandoned_and_expelled_are_not_requests(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    former = await _add_membership(project["id_project"], ANA_ID, "active", is_leader=True)
    await _set_membership_status(former, "abandoned")
    another = await _create(client, admin, await _section_year(client, admin, name="3K7"))
    expelled = await _add_membership(another["id_project"], ANA_ID, "active")
    await _set_membership_status(expelled, "expelled")

    body = (await client.get("/me/project", headers=await login(STUDENT))).json()
    assert body == {"project": None, "requests": []}
