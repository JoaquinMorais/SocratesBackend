from datetime import date, datetime, timezone

from config.database import SessionLocal
from models import Project, Student, StudentProject, User
from tests.helpers import PASSWORD, STUDENT, SUPER_ADMIN
from utils.statuses import get_status

LUIS = "100002@sistemas.frc.utn.edu.ar"
ANA_ID, LUIS_ID = 1, 2
URL = "/projects"
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
    r = await client.post(URL, json={"id_section_year": id_section_year}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def _overview(client, headers, id_project: int, **params):
    return await client.get(f"{URL}/{id_project}/overview", params=params, headers=headers)


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


async def _set_status(id_project: int, code: str) -> None:
    async with SessionLocal() as s:
        status = await get_status(s, "project", code)
        project = await s.get(Project, id_project)
        project.id_status = status.id_status
        s.add(project)
        await s.commit()


async def _patch(client, admin, id_project: int, **fields) -> None:
    r = await client.patch(f"{URL}/{id_project}", json=fields, headers=admin)
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
    assert (await client.get(f"{URL}/1/overview")).status_code == 401


async def test_unknown_project(client, login):
    assert (await _overview(client, await login(SUPER_ADMIN), 999)).status_code == 404


async def test_private_overview_hidden_from_outsiders(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(project["id_project"], ANA_ID, is_leader=True)
    await _patch(client, admin, project["id_project"], privacy="private")
    await _set_status(project["id_project"], "in_idea")

    luis = await login(LUIS)  # alumno no miembro
    prof = await login(await make_professor("prof@frc.utn.edu.ar"))  # no asignado
    assert (await _overview(client, luis, project["id_project"])).status_code == 403
    assert (await _overview(client, prof, project["id_project"])).status_code == 403


async def test_non_privileged_cannot_filter_status(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(project["id_project"], ANA_ID, is_leader=True)
    prof = await login(await make_professor("prof@frc.utn.edu.ar"))
    r = await _overview(client, prof, project["id_project"], status="pending_approval")
    assert r.status_code == 403


# ---------- visibilidad ----------
async def test_uninsured_overview_shows_detail_and_members(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(project["id_project"], ANA_ID, is_leader=True, enrolled_at=T1)
    await _add_membership(project["id_project"], LUIS_ID, enrolled_at=T2)
    await _patch(client, admin, project["id_project"], name="Proyecto", privacy="private")

    prof = await login(await make_professor("prof@frc.utn.edu.ar"))
    body = (await _overview(client, prof, project["id_project"])).json()
    assert body["restricted"] is False
    assert body["name"] == "Proyecto"  # uninsured se trata como público
    assert body["privacy"] == "public"  # privacidad efectiva
    assert len(body["members"]) == 2
    assert body["responsible"]["id_student"] == ANA_ID


async def test_public_overview_full_detail_and_members(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(project["id_project"], ANA_ID, is_leader=True, enrolled_at=T1)
    await _add_membership(project["id_project"], LUIS_ID, enrolled_at=T2)
    await _patch(client, admin, project["id_project"], name="Proyecto")
    await _set_status(project["id_project"], "in_idea")

    prof = await login(await make_professor("prof@frc.utn.edu.ar"))
    body = (await _overview(client, prof, project["id_project"])).json()
    assert body["restricted"] is False and body["name"] == "Proyecto"
    assert len(body["members"]) == 2
    assert body["responsible"]["id_student"] == ANA_ID
    assert body["responsible"]["is_leader"] is True


async def test_protected_overview_basic_for_outsiders(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(project["id_project"], ANA_ID, is_leader=True)
    await _add_membership(project["id_project"], LUIS_ID)
    await _patch(client, admin, project["id_project"], name="Proyecto", privacy="protected")
    await _set_status(project["id_project"], "in_idea")

    prof = await login(await make_professor("prof@frc.utn.edu.ar"))
    body = (await _overview(client, prof, project["id_project"])).json()
    assert body["restricted"] is True
    assert body["name"] is None
    assert len(body["members"]) == 2  # igual ve los integrantes
    assert body["responsible"]["id_student"] == ANA_ID


async def test_protected_overview_full_for_privileged(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    project = await _create(client, admin, sy)
    await _add_membership(project["id_project"], ANA_ID, is_leader=True)
    await _patch(client, admin, project["id_project"], name="Proyecto", privacy="protected")
    await _set_status(project["id_project"], "in_idea")
    mail = await make_professor("prof@frc.utn.edu.ar")
    await _assign_professor(client, admin, mail, sy)

    for headers in (await login(STUDENT), await login(mail), admin):
        body = (await _overview(client, headers, project["id_project"])).json()
        assert body["restricted"] is False and body["name"] == "Proyecto"


async def test_private_overview_full_for_privileged(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    project = await _create(client, admin, sy)
    await _add_membership(project["id_project"], ANA_ID, is_leader=True)
    await _patch(client, admin, project["id_project"], name="Proyecto", privacy="private")
    await _set_status(project["id_project"], "in_idea")
    mail = await make_professor("prof@frc.utn.edu.ar")
    await _assign_professor(client, admin, mail, sy)

    for headers in (await login(STUDENT), await login(mail), admin):
        r = await _overview(client, headers, project["id_project"])
        assert r.status_code == 200 and r.json()["name"] == "Proyecto"


async def test_overview_without_leader(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    body = (await _overview(client, admin, project["id_project"])).json()
    assert body["members"] == []
    assert body["responsible"] is None


# ---------- filtro de estados ----------
async def test_overview_default_members_are_active_and_finished(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    extra = await _make_student(900001)
    await _add_membership(project["id_project"], ANA_ID, "active", is_leader=True, enrolled_at=T1)
    await _add_membership(project["id_project"], LUIS_ID, "finished", enrolled_at=T2)
    await _add_membership(project["id_project"], extra, "pending_approval", enrolled_at=T2)

    body = (await _overview(client, admin, project["id_project"])).json()
    assert {m["id_student"] for m in body["members"]} == {ANA_ID, LUIS_ID}
    assert body["responsible"]["id_student"] == ANA_ID


async def test_overview_privileged_can_filter_status(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    extra = await _make_student(900002)
    await _add_membership(project["id_project"], ANA_ID, "active", is_leader=True)
    await _add_membership(project["id_project"], extra, "pending_approval")

    body = (await _overview(client, admin, project["id_project"], status="pending_approval")).json()
    assert [m["id_student"] for m in body["members"]] == [extra]
    assert body["responsible"]["id_student"] == ANA_ID  # el jefe se resuelve aparte del filtro

    both = (await _overview(client, admin, project["id_project"], status=["active", "pending_approval"])).json()
    assert {m["id_student"] for m in both["members"]} == {ANA_ID, extra}


async def test_overview_invalid_status(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    assert (await _overview(client, admin, project["id_project"], status="nope")).status_code == 422


# ---------- datos del integrante ----------
async def test_overview_member_fields_and_order(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(project["id_project"], ANA_ID, "active", is_leader=True, enrolled_at=T2)
    await _add_membership(project["id_project"], LUIS_ID, "active", enrolled_at=T1)

    body = (await _overview(client, admin, project["id_project"])).json()
    first = body["members"][0]
    assert first["is_leader"] is True and first["id_student"] == ANA_ID  # el jefe va primero
    assert {
        "id_student_project",
        "id_student",
        "first_name",
        "last_name",
        "legajo",
        "is_leader",
        "enrolled_at",
        "status",
    } <= set(first)
    assert "email" not in first
    assert "T" in first["enrolled_at"]  # datetime ISO
