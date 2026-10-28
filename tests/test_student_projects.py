from datetime import date, datetime, timezone

from sqlmodel import select

from config.database import SessionLocal
from models import Project, Student, StudentProject, User
from tests.helpers import PASSWORD, STUDENT, SUPER_ADMIN
from utils.statuses import get_status

LUIS = "100002@sistemas.frc.utn.edu.ar"
ANA_ID, LUIS_ID = 1, 2  # ids de los alumnos del seed
URL = "/projects"

# Fechas de inscripción para probar la antigüedad y la sucesión de jefe.
T1 = datetime(2025, 3, 1, tzinfo=timezone.utc)
T2 = datetime(2025, 3, 2, tzinfo=timezone.utc)
T3 = datetime(2025, 3, 3, tzinfo=timezone.utc)


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


async def _join(client, headers, id_project: int):
    return await client.post(f"{URL}/{id_project}/members", headers=headers)


async def _members(client, headers, id_project: int, **params):
    return await client.get(f"{URL}/{id_project}/members", params=params, headers=headers)


async def _decide(client, headers, id_project: int, id_student_project: int, status_code: str):
    return await client.patch(
        f"{URL}/{id_project}/members/{id_student_project}",
        json={"status": status_code},
        headers=headers,
    )


async def _abandon(client, headers, id_project: int, id_student_project: int):
    return await client.post(
        f"{URL}/{id_project}/members/{id_student_project}/abandon", headers=headers
    )


async def _expel(client, headers, id_project: int, id_student_project: int):
    return await client.post(
        f"{URL}/{id_project}/members/{id_student_project}/expel", headers=headers
    )


async def _add(client, headers, id_project: int, id_student: int):
    return await client.post(
        f"{URL}/{id_project}/members/{id_student}", headers=headers
    )


async def _leader(client, headers, id_project: int, id_student_project: int):
    return await client.post(
        f"{URL}/{id_project}/members/{id_student_project}/leader", headers=headers
    )


async def _find_membership(id_project: int, id_student: int) -> int:
    async with SessionLocal() as s:
        return (
            await s.exec(
                select(StudentProject.id_student_project).where(
                    StudentProject.id_project == id_project,
                    StudentProject.id_student == id_student,
                )
            )
        ).first()


async def _set_status(id_project: int, code: str) -> None:
    async with SessionLocal() as s:
        status = await get_status(s, "project", code)
        project = await s.get(Project, id_project)
        project.id_status = status.id_status
        s.add(project)
        await s.commit()


async def _add_membership(
    id_project: int,
    id_student: int,
    code: str = "active",
    is_leader: bool = False,
    enrolled_at: datetime | None = None,
) -> int:
    async with SessionLocal() as s:
        membership_status = await get_status(s, "student_project", code)
        extra = {"enrolled_at": enrolled_at} if enrolled_at is not None else {}
        membership = StudentProject(
            id_student=id_student,
            id_project=id_project,
            id_status=membership_status.id_status,
            is_leader=is_leader,
            **extra,
        )
        s.add(membership)
        await s.commit()
        return membership.id_student_project


async def _make_student(legajo: int = 900001) -> int:
    """Crea un alumno directo en la BD y devuelve su id."""
    async with SessionLocal() as s:
        user = User(
            first_name="Nuevo",
            last_name="Alumno",
            legajo=legajo,
            birth_date=date(2003, 1, 1),
        )
        user.set_password(PASSWORD)
        s.add(user)
        await s.flush()
        s.add(Student(id_student=user.id_user, enrollment_year=2021))
        await s.commit()
        return user.id_user


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
    ends = [
        ("POST", f"{URL}/1/members", None),
        ("GET", f"{URL}/1/members", None),
        ("PATCH", f"{URL}/1/members/1", {"status": "active"}),
        ("POST", f"{URL}/1/members/1/abandon", None),
        ("POST", f"{URL}/1/members/1/expel", None),
        ("POST", f"{URL}/1/members/1/leader", None),
    ]
    for method, url, body in ends:
        r = await client.request(method, url, json=body)
        assert r.status_code == 401, (method, url)


async def test_professor_cannot_join(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    assert (await _join(client, admin, project["id_project"])).status_code == 403


async def test_non_leader_cannot_decide(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    project = await _create(client, admin, sy)
    await _join(client, await login(STUDENT), project["id_project"])  # Ana, jefa
    pending = (await _join(client, await login(LUIS), project["id_project"])).json()

    for headers in (await login(LUIS), await login(await make_professor("prof@frc.utn.edu.ar")), admin):
        r = await _decide(client, headers, project["id_project"], pending["id_student_project"], "active")
        assert r.status_code == 403


async def test_professor_cannot_abandon(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    ana_membership = (await _join(client, await login(STUDENT), project["id_project"])).json()
    prof = await login(await make_professor("prof@frc.utn.edu.ar"))
    r = await _abandon(client, prof, project["id_project"], ana_membership["id_student_project"])
    assert r.status_code == 403


# ---------- unirse ----------
async def test_first_member_becomes_leader_and_active(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    r = await _join(client, await login(STUDENT), project["id_project"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id_student"] == ANA_ID
    assert body["is_leader"] is True
    assert body["status"]["code"] == "active"


async def test_second_member_is_pending_and_not_leader(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    await _join(client, await login(STUDENT), project["id_project"])
    r = await _join(client, await login(LUIS), project["id_project"])
    assert r.status_code == 201, r.text
    assert r.json()["is_leader"] is False
    assert r.json()["status"]["code"] == "pending_approval"


async def test_cannot_join_insured_project(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    await _set_status(project["id_project"], "in_idea")
    assert (await _join(client, await login(STUDENT), project["id_project"])).status_code == 409


async def test_join_unknown_project(client, login):
    assert (await _join(client, await login(STUDENT), 999)).status_code == 404


async def test_cannot_request_twice(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    ana = await login(STUDENT)
    assert (await _join(client, ana, project["id_project"])).status_code == 201
    assert (await _join(client, ana, project["id_project"])).status_code == 409  # ya es miembro
    luis = await login(LUIS)
    assert (await _join(client, luis, project["id_project"])).status_code == 201
    assert (await _join(client, luis, project["id_project"])).status_code == 409  # ya pidió


async def test_rejected_can_request_again(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    ana = await login(STUDENT)
    ana_membership = (await _join(client, ana, project["id_project"])).json()
    luis = await login(LUIS)
    pending = (await _join(client, luis, project["id_project"])).json()

    assert (await _decide(client, ana, project["id_project"], pending["id_student_project"], "rejected")).status_code == 200
    r = await _join(client, luis, project["id_project"])
    assert r.status_code == 200, r.text  # se vuelve a enviar la solicitud
    assert r.json()["status"]["code"] == "pending_approval"
    assert ana_membership["is_leader"] is True


async def test_cannot_join_empty_group_when_member_elsewhere(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p1 = await _create(client, admin, sy)
    p2 = await _create(client, admin, sy)
    ana = await login(STUDENT)
    await _join(client, ana, p1["id_project"])  # Ana queda member (jefa)
    r = await _join(client, ana, p2["id_project"])
    assert r.status_code == 409
    assert "abandon" in r.json()["detail"].lower()


async def test_member_elsewhere_cannot_request_join(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p1 = await _create(client, admin, sy)
    p2 = await _create(client, admin, sy)
    await _join(client, await login(STUDENT), p1["id_project"])  # Ana member
    await _join(client, await login(LUIS), p2["id_project"])  # Luis jefe de p2
    r = await _join(client, await login(STUDENT), p2["id_project"])
    assert r.status_code == 409
    assert "abandon" in r.json()["detail"].lower()


async def test_member_elsewhere_cannot_resend_rejected_request(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p1 = await _create(client, admin, sy)
    p2 = await _create(client, admin, sy)
    ana = await login(STUDENT)
    await _join(client, ana, p2["id_project"])  # Ana leader of p2
    luis = await login(LUIS)
    pending = (await _join(client, luis, p2["id_project"])).json()
    await _decide(client, ana, p2["id_project"], pending["id_student_project"], "rejected")
    # ahora Luis pasa a ser member en otro grupo
    await _join(client, luis, p1["id_project"])  # p1 vacío -> queda leader activo
    r = await _join(client, luis, p2["id_project"])
    assert r.status_code == 409
    assert "abandon" in r.json()["detail"].lower()


async def test_student_with_only_pending_elsewhere_can_still_request(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p1 = await _create(client, admin, sy)
    p2 = await _create(client, admin, sy)
    await _join(client, await login(STUDENT), p1["id_project"])  # Ana jefa de p1
    luis = await login(LUIS)
    r_pending = await _join(client, luis, p1["id_project"])  # solo pending en p1
    assert r_pending.status_code == 201
    # p2 vacío -> Luis puede entrar y queda como jefe/active (se rechazan sus otras pending)
    r = await _join(client, luis, p2["id_project"])
    assert r.status_code == 201
    assert r.json()["status"]["code"] == "active"
    assert r.json()["is_leader"] is True
    members = (await _members(client, await login(STUDENT), p1["id_project"])).json()["items"]
    luis_row = next(m for m in members if m["id_student"] == LUIS_ID)
    assert luis_row["status"]["code"] == "rejected"


async def test_becoming_member_rejects_other_pending(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p1 = await _create(client, admin, sy)
    p2 = await _create(client, admin, sy)
    ana = await login(STUDENT)
    await _join(client, ana, p1["id_project"])  # Ana jefa de p1
    luis = await login(LUIS)
    await _join(client, luis, p1["id_project"])  # Luis pending en p1
    await _join(client, luis, p2["id_project"])  # Luis queda member (jefe) de p2

    members = (await _members(client, ana, p1["id_project"])).json()["items"]
    luis_row = next(m for m in members if m["id_student"] == LUIS_ID)
    assert luis_row["status"]["code"] == "rejected"


# ---------- aceptar / rechazar ----------
async def test_leader_accepts_request(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    ana = await login(STUDENT)
    await _join(client, ana, project["id_project"])
    pending = (await _join(client, await login(LUIS), project["id_project"])).json()

    r = await _decide(client, ana, project["id_project"], pending["id_student_project"], "active")
    assert r.status_code == 200, r.text
    assert r.json()["status"]["code"] == "active"
    assert r.json()["is_leader"] is False


async def test_leader_rejects_request(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    ana = await login(STUDENT)
    await _join(client, ana, project["id_project"])
    pending = (await _join(client, await login(LUIS), project["id_project"])).json()

    r = await _decide(client, ana, project["id_project"], pending["id_student_project"], "rejected")
    assert r.status_code == 200
    assert r.json()["status"]["code"] == "rejected"


async def test_decide_invalid_transition(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    ana = await login(STUDENT)
    ana_membership = (await _join(client, ana, project["id_project"])).json()  # active
    # active -> active y active -> rejected no son transiciones válidas.
    assert (await _decide(client, ana, project["id_project"], ana_membership["id_student_project"], "active")).status_code == 409
    assert (await _decide(client, ana, project["id_project"], ana_membership["id_student_project"], "rejected")).status_code == 409


async def test_accept_when_student_already_member(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p1 = await _create(client, admin, sy)
    p2 = await _create(client, admin, sy)
    ana = await login(STUDENT)
    await _join(client, ana, p1["id_project"])  # Ana jefa de p1
    await _add_membership(p2["id_project"], LUIS_ID, "active")  # Luis ya es member de p2

    luis = await login(LUIS)
    r_pending = await _join(client, luis, p1["id_project"])
    # ahora el join también bloquea al ser member en otro grupo
    assert r_pending.status_code == 409
    assert "abandon" in r_pending.json()["detail"].lower()


async def test_decide_membership_not_found(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p1 = await _create(client, admin, sy)
    p2 = await _create(client, admin, sy)
    ana = await login(STUDENT)
    await _join(client, ana, p1["id_project"])
    other = (await _join(client, await login(LUIS), p2["id_project"])).json()  # membership de p2

    assert (await _decide(client, ana, p1["id_project"], 999, "active")).status_code == 404
    assert (await _decide(client, ana, p1["id_project"], other["id_student_project"], "active")).status_code == 404


async def test_decide_invalid_body(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    ana = await login(STUDENT)
    ana_membership = (await _join(client, ana, project["id_project"])).json()
    url = f"{URL}/{project['id_project']}/members/{ana_membership['id_student_project']}"
    for body in ({}, {"status": "abandoned"}, {"status": "active", "extra": 1}):
        r = await client.patch(url, json=body, headers=ana)
        assert r.status_code == 422, body


# ---------- abandonar ----------
async def test_member_can_abandon(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    ana = await login(STUDENT)
    ana_membership = (await _join(client, ana, project["id_project"])).json()

    r = await _abandon(client, ana, project["id_project"], ana_membership["id_student_project"])
    assert r.status_code == 204, r.text

    members = (await _members(client, admin, project["id_project"])).json()["items"]
    assert members[0]["status"]["code"] == "abandoned"
    assert members[0]["is_leader"] is False


async def test_cannot_abandon_someone_else(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    ana_membership = (await _join(client, await login(STUDENT), project["id_project"])).json()
    luis = await login(LUIS)
    await _join(client, luis, project["id_project"])  # Luis pending

    r = await _abandon(client, luis, project["id_project"], ana_membership["id_student_project"])
    assert r.status_code == 403


async def test_cannot_abandon_pending(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    await _join(client, await login(STUDENT), project["id_project"])  # Ana jefa
    luis = await login(LUIS)
    luis_membership = (await _join(client, luis, project["id_project"])).json()  # pending

    r = await _abandon(client, luis, project["id_project"], luis_membership["id_student_project"])
    assert r.status_code == 409


async def test_cannot_abandon_insured_project(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    ana = await login(STUDENT)
    ana_membership = (await _join(client, ana, project["id_project"])).json()
    await _set_status(project["id_project"], "in_idea")

    r = await _abandon(client, ana, project["id_project"], ana_membership["id_student_project"])
    assert r.status_code == 409


async def test_abandon_unknown_membership(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    await _join(client, await login(STUDENT), project["id_project"])
    r = await _abandon(client, await login(STUDENT), project["id_project"], 999)
    assert r.status_code == 404


async def test_leader_abandon_promotes_oldest_active(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    extra = await _make_student(900001)
    await _add_membership(project["id_project"], ANA_ID, "active", is_leader=True, enrolled_at=T3)
    await _add_membership(project["id_project"], extra, "active", enrolled_at=T2)
    await _add_membership(project["id_project"], LUIS_ID, "active", enrolled_at=T1)  # el más antiguo
    ana_membership = await _find_membership(project["id_project"], ANA_ID)

    r = await _abandon(client, await login(STUDENT), project["id_project"], ana_membership)
    assert r.status_code == 204, r.text

    members = (await _members(client, admin, project["id_project"])).json()["items"]
    leader = next(m for m in members if m["is_leader"])
    assert leader["id_student"] == LUIS_ID  # el active más antiguo


async def test_leader_abandon_without_successor_leaves_no_leader(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    ana = await login(STUDENT)
    ana_membership = (await _join(client, ana, project["id_project"])).json()

    assert (await _abandon(client, ana, project["id_project"], ana_membership["id_student_project"])).status_code == 204
    members = (await _members(client, admin, project["id_project"])).json()["items"]
    assert members[0]["is_leader"] is False
    assert members[0]["status"]["code"] == "abandoned"


# ---------- expulsar ----------
async def test_professor_can_expel(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    project = await _create(client, admin, sy)
    await _add_membership(project["id_project"], ANA_ID, "active", is_leader=True, enrolled_at=T1)
    await _add_membership(project["id_project"], LUIS_ID, "active", enrolled_at=T2)
    mail = await make_professor("prof@frc.utn.edu.ar")
    await _assign_professor(client, admin, mail, sy)
    luis_membership = await _find_membership(project["id_project"], LUIS_ID)

    r = await _expel(client, await login(mail), project["id_project"], luis_membership)
    assert r.status_code == 204, r.text
    members = (await _members(client, admin, project["id_project"])).json()["items"]
    assert next(m for m in members if m["id_student"] == LUIS_ID)["status"]["code"] == "expelled"


async def test_super_admin_can_expel(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(project["id_project"], ANA_ID, "active", is_leader=True)
    await _add_membership(project["id_project"], LUIS_ID, "active")
    luis_membership = await _find_membership(project["id_project"], LUIS_ID)

    assert (await _expel(client, admin, project["id_project"], luis_membership)).status_code == 204


async def test_unassigned_professor_cannot_expel(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(project["id_project"], ANA_ID, "active", is_leader=True)
    luis_membership = await _add_membership(project["id_project"], LUIS_ID, "active")
    other = await login(await make_professor("otro@frc.utn.edu.ar"))
    assert (await _expel(client, other, project["id_project"], luis_membership)).status_code == 403


async def test_leader_cannot_expel(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(project["id_project"], ANA_ID, "active", is_leader=True)
    luis_membership = await _add_membership(project["id_project"], LUIS_ID, "active")
    r = await _expel(client, await login(STUDENT), project["id_project"], luis_membership)
    assert r.status_code == 403


async def test_cannot_expel_pending(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(project["id_project"], ANA_ID, "active", is_leader=True)
    luis_membership = await _add_membership(project["id_project"], LUIS_ID, "pending_approval")
    assert (await _expel(client, admin, project["id_project"], luis_membership)).status_code == 409


async def test_cannot_expel_in_insured_project(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(project["id_project"], ANA_ID, "active", is_leader=True)
    luis_membership = await _add_membership(project["id_project"], LUIS_ID, "active")
    await _set_status(project["id_project"], "in_idea")
    assert (await _expel(client, admin, project["id_project"], luis_membership)).status_code == 409


async def test_expel_unknown_membership(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    assert (await _expel(client, admin, project["id_project"], 999)).status_code == 404


async def test_expel_leader_promotes_oldest_active(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    extra = await _make_student(900002)
    await _add_membership(project["id_project"], ANA_ID, "active", is_leader=True, enrolled_at=T3)
    await _add_membership(project["id_project"], LUIS_ID, "active", enrolled_at=T1)  # más antiguo
    await _add_membership(project["id_project"], extra, "active", enrolled_at=T2)
    ana_membership = await _find_membership(project["id_project"], ANA_ID)

    assert (await _expel(client, admin, project["id_project"], ana_membership)).status_code == 204
    members = (await _members(client, admin, project["id_project"])).json()["items"]
    leader = next(m for m in members if m["is_leader"])
    assert leader["id_student"] == LUIS_ID


# ---------- añadir integrante (profesor / super admin) ----------
async def test_add_requires_authentication(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    project = await _create(client, admin, sy)
    student_id = await _make_student(900010)
    assert (await _add(client, {}, project["id_project"], student_id)).status_code == 401


async def test_student_cannot_add_member(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    project = await _create(client, admin, sy)
    student_id = await _make_student(900011)
    r = await _add(client, await login(STUDENT), project["id_project"], student_id)
    assert r.status_code == 403


async def test_unassigned_professor_cannot_add_member(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    project = await _create(client, admin, sy)
    student_id = await _make_student(900012)
    other = await login(await make_professor("otro@frc.utn.edu.ar"))
    assert (await _add(client, other, project["id_project"], student_id)).status_code == 403


async def test_professor_can_add_member(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    project = await _create(client, admin, sy)
    mail = await make_professor("prof@frc.utn.edu.ar")
    await _assign_professor(client, admin, mail, sy)
    student_id = await _make_student(900013)
    r = await _add(client, await login(mail), project["id_project"], student_id)
    assert r.status_code == 201, r.text
    assert r.json()["status"]["code"] == "active"
    assert r.json()["is_leader"] is True  # grupo vacío: el añadido es jefe


async def test_super_admin_can_add_member(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    project = await _create(client, admin, sy)
    await _add_membership(project["id_project"], ANA_ID, "active", is_leader=True)
    student_id = await _make_student(900014)
    r = await _add(client, admin, project["id_project"], student_id)
    assert r.status_code == 201, r.text
    assert r.json()["status"]["code"] == "active"
    assert r.json()["is_leader"] is False


async def test_add_unknown_student(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    project = await _create(client, admin, sy)
    assert (await _add(client, admin, project["id_project"], 999999)).status_code == 404


async def test_add_unknown_project(client, login):
    admin = await login(SUPER_ADMIN)
    student_id = await _make_student(900015)
    assert (await _add(client, admin, 999999, student_id)).status_code == 404


async def test_cannot_add_in_insured_project(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    project = await _create(client, admin, sy)
    student_id = await _make_student(900016)
    await _set_status(project["id_project"], "in_idea")
    assert (await _add(client, admin, project["id_project"], student_id)).status_code == 409


async def test_cannot_add_already_member(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    project = await _create(client, admin, sy)
    await _add_membership(project["id_project"], ANA_ID, "active", is_leader=True)
    r = await _add(client, admin, project["id_project"], ANA_ID)
    assert r.status_code == 409


async def test_cannot_add_member_of_another_project(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p1 = await _create(client, admin, sy)
    p2 = await _create(client, admin, sy)
    await _add_membership(p1["id_project"], ANA_ID, "active", is_leader=True)
    r = await _add(client, admin, p2["id_project"], ANA_ID)
    assert r.status_code == 409


async def test_add_reactivates_rejected_membership(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    project = await _create(client, admin, sy)
    await _add_membership(project["id_project"], LUIS_ID, "rejected")
    r = await _add(client, admin, project["id_project"], LUIS_ID)
    assert r.status_code == 200, r.text
    assert r.json()["status"]["code"] == "active"


async def test_add_rejects_other_pending_requests(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    p1 = await _create(client, admin, sy)
    p2 = await _create(client, admin, sy)
    # Luis tiene una solicitud pending en p2
    await _add_membership(p2["id_project"], LUIS_ID, "pending_approval")
    await _add(client, admin, p1["id_project"], LUIS_ID)
    # la solicitud pendiente en p2 pasa a rejected
    members = (await _members(client, admin, p2["id_project"], status="pending_approval")).json()["items"]
    assert all(m["id_student"] != LUIS_ID for m in members)


# ---------- delegar jefatura ----------
async def test_leader_can_transfer_leadership(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    ana = await login(STUDENT)
    await _join(client, ana, project["id_project"])  # Ana jefa
    luis_membership = (await _join(client, await login(LUIS), project["id_project"])).json()
    luis_id = luis_membership["id_student_project"]
    # Luis está pending: primero la jefa lo acepta.
    await _decide(client, ana, project["id_project"], luis_id, "active")

    r = await _leader(client, ana, project["id_project"], luis_id)
    assert r.status_code == 200, r.text
    assert r.json()["is_leader"] is True and r.json()["id_student"] == LUIS_ID

    members = (await _members(client, admin, project["id_project"])).json()["items"]
    assert next(m for m in members if m["id_student"] == ANA_ID)["is_leader"] is False


async def test_cannot_transfer_to_pending(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    ana = await login(STUDENT)
    await _join(client, ana, project["id_project"])  # Ana jefa
    pending = (await _join(client, await login(LUIS), project["id_project"])).json()
    r = await _leader(client, ana, project["id_project"], pending["id_student_project"])
    assert r.status_code == 409


async def test_cannot_transfer_to_self(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    ana = await login(STUDENT)
    ana_membership = (await _join(client, ana, project["id_project"])).json()
    r = await _leader(client, ana, project["id_project"], ana_membership["id_student_project"])
    assert r.status_code == 409


async def test_non_leader_cannot_transfer(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(project["id_project"], ANA_ID, "active", is_leader=True, enrolled_at=T1)
    luis_membership = await _add_membership(project["id_project"], LUIS_ID, "active", enrolled_at=T2)
    # Luis es active pero no jefe: no puede delegar (ni siquiera a sí mismo).
    r = await _leader(client, await login(LUIS), project["id_project"], luis_membership)
    assert r.status_code == 403


async def test_transfer_allowed_in_insured_project(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(project["id_project"], ANA_ID, "active", is_leader=True, enrolled_at=T1)
    luis_membership = await _add_membership(project["id_project"], LUIS_ID, "active", enrolled_at=T2)
    await _set_status(project["id_project"], "in_progress")

    r = await _leader(client, await login(STUDENT), project["id_project"], luis_membership)
    assert r.status_code == 200, r.text


async def test_cannot_transfer_in_final_project(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    await _add_membership(project["id_project"], ANA_ID, "active", is_leader=True, enrolled_at=T1)
    luis_membership = await _add_membership(project["id_project"], LUIS_ID, "active", enrolled_at=T2)
    await _set_status(project["id_project"], "cancelled")

    r = await _leader(client, await login(STUDENT), project["id_project"], luis_membership)
    assert r.status_code == 409


async def test_transfer_unknown_membership(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    await _join(client, await login(STUDENT), project["id_project"])
    r = await _leader(client, await login(STUDENT), project["id_project"], 999)
    assert r.status_code == 404


# ---------- consultar ----------
async def test_outsider_cannot_list(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    await _join(client, await login(STUDENT), project["id_project"])
    assert (await _members(client, await login(LUIS), project["id_project"])).status_code == 403


async def test_member_can_list_and_leader_is_first(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    ana = await login(STUDENT)
    await _join(client, ana, project["id_project"])
    await _join(client, await login(LUIS), project["id_project"])

    body = (await _members(client, ana, project["id_project"])).json()
    assert body["total"] == 2
    assert body["items"][0]["id_student"] == ANA_ID and body["items"][0]["is_leader"] is True
    first = body["items"][0]
    assert {"id_student_project", "id_student", "first_name", "last_name", "legajo", "is_leader", "enrolled_at", "status"} <= set(first)
    assert "email" not in first
    assert "T" in first["enrolled_at"]  # datetime ISO


async def test_staff_can_list(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    project = await _create(client, admin, sy)
    await _join(client, await login(STUDENT), project["id_project"])
    mail = await make_professor("prof@frc.utn.edu.ar")
    await _assign_professor(client, admin, mail, sy)

    assert (await _members(client, admin, project["id_project"])).status_code == 200
    assert (await _members(client, await login(mail), project["id_project"])).status_code == 200


async def test_list_unknown_project(client, login):
    assert (await _members(client, await login(SUPER_ADMIN), 999)).status_code == 404


async def test_list_filter_and_pagination(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    ana = await login(STUDENT)
    await _join(client, ana, project["id_project"])
    pending = (await _join(client, await login(LUIS), project["id_project"])).json()

    only_pending = (await _members(client, ana, project["id_project"], status="pending_approval")).json()
    assert only_pending["total"] == 1
    assert only_pending["items"][0]["id_student"] == LUIS_ID
    assert (await _members(client, ana, project["id_project"], status="nope")).status_code == 422

    page = (await _members(client, ana, project["id_project"], limit=1)).json()
    assert len(page["items"]) == 1 and page["total"] == 2
    assert (await _members(client, ana, project["id_project"], limit=0)).status_code == 422
    assert pending["status"]["code"] == "pending_approval"
