from config.database import SessionLocal
from models import Project
from tests.helpers import (
    STUDENT,
    SUPER_ADMIN,
    assign_professor,
    section_year,
)
from utils.statuses import get_status

URL = "/me/section-year"
PROJECTS = "/me/section-year/projects"
ANA_ID, LUIS_ID = 1, 2
LUIS = "100002@sistemas.frc.utn.edu.ar"


async def _enroll(client, headers, id_student: int, id_section_year: int) -> None:
    r = await client.post(
        "/student-section-years",
        json={"id_student": id_student, "id_section_year": id_section_year},
        headers=headers,
    )
    assert r.status_code == 201, r.text


async def _project(client, headers, id_section_year: int) -> dict:
    r = await client.post(
        "/projects", json={"id_section_year": id_section_year}, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _set_status(id_project: int, code: str) -> None:
    async with SessionLocal() as s:
        status = await get_status(s, "project", code)
        project = await s.get(Project, id_project)
        project.id_status = status.id_status
        s.add(project)
        await s.commit()


async def _set_privacy(id_project: int, privacy: str, name: str) -> None:
    async with SessionLocal() as s:
        project = await s.get(Project, id_project)
        project.privacy = privacy
        project.name = name
        s.add(project)
        await s.commit()


# ---------- permisos ----------
async def test_requires_authentication(client):
    assert (await client.get(URL)).status_code == 401
    assert (await client.get(PROJECTS)).status_code == 401


# ---------- profesores ----------
async def test_professor_gets_latest_section_year(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    mail = await make_professor("prof-actual@frc.utn.edu.ar")
    sy_2025 = await section_year(client, admin, "3K1", 2025)
    sy_2026 = await section_year(client, admin, "3K2", 2026)
    await assign_professor(client, admin, mail, sy_2025)
    await assign_professor(client, admin, mail, sy_2026)
    p_2025 = await _project(client, admin, sy_2025)
    p_2026 = await _project(client, admin, sy_2026)

    headers = await login(mail)
    body = (await client.get(URL, headers=headers)).json()
    assert [s["id_section_year"] for s in body["section_years"]] == [sy_2026]
    assert body["section_years"][0]["year"] == 2026

    listing = (await client.get(PROJECTS, headers=headers)).json()
    assert [p["id_project"] for p in listing["items"]] == [p_2026["id_project"]]
    assert p_2025["id_project"] not in [p["id_project"] for p in listing["items"]]


async def test_professor_with_two_commissions_in_latest_year(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    mail = await make_professor("prof-doble@frc.utn.edu.ar")
    sy_a = await section_year(client, admin, "3K1", 2026)
    sy_b = await section_year(client, admin, "3K2", 2026)
    await assign_professor(client, admin, mail, sy_a)
    await assign_professor(client, admin, mail, sy_b)
    p_a = await _project(client, admin, sy_a)
    p_b = await _project(client, admin, sy_b)

    headers = await login(mail)
    body = (await client.get(URL, headers=headers)).json()
    assert [s["id_section_year"] for s in body["section_years"]] == [sy_a, sy_b]
    listing = (await client.get(PROJECTS, headers=headers)).json()
    assert {p["id_project"] for p in listing["items"]} == {
        p_a["id_project"],
        p_b["id_project"],
    }
    assert listing["total"] == 2


# ---------- alumnos ----------
async def test_student_gets_latest_cursada_year(client, login):
    admin = await login(SUPER_ADMIN)
    sy_2025 = await section_year(client, admin, "3K1", 2025)
    sy_2026 = await section_year(client, admin, "3K2", 2026)
    await _enroll(client, admin, ANA_ID, sy_2025)
    await _enroll(client, admin, ANA_ID, sy_2026)
    p_2025 = await _project(client, admin, sy_2025)
    p_2026 = await _project(client, admin, sy_2026)

    headers = await login(STUDENT)
    body = (await client.get(URL, headers=headers)).json()
    assert [s["id_section_year"] for s in body["section_years"]] == [sy_2026]
    listing = (await client.get(PROJECTS, headers=headers)).json()
    assert [p["id_project"] for p in listing["items"]] == [p_2026["id_project"]]
    assert p_2025["id_project"] not in [p["id_project"] for p in listing["items"]]


async def test_student_falls_back_to_current_group(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2025)
    project = await _project(client, admin, sy)
    # Luis se une: queda `active` (y jefe) porque el grupo está vacío.
    r = await client.post(
        f"/projects/{project['id_project']}/members", headers=await login(LUIS)
    )
    assert r.status_code == 201, r.text

    headers = await login(LUIS)
    body = (await client.get(URL, headers=headers)).json()
    assert [s["id_section_year"] for s in body["section_years"]] == [sy]
    listing = (await client.get(PROJECTS, headers=headers)).json()
    assert [p["id_project"] for p in listing["items"]] == [project["id_project"]]


# ---------- sin curso actual ----------
async def test_no_current_section_year(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sin_asignaciones = await make_professor("prof-sin-curso@frc.utn.edu.ar")
    cases = [
        await login(sin_asignaciones),  # profesor sin asignaciones
        await login(STUDENT),  # Ana, sin cursadas ni grupo
        admin,  # super admin que no dicta
    ]
    for headers in cases:
        body = (await client.get(URL, headers=headers)).json()
        assert body == {"section_years": []}
        listing = (await client.get(PROJECTS, headers=headers)).json()
        assert listing == {"items": [], "total": 0, "limit": 50, "offset": 0}


# ---------- visibilidad ----------
async def test_projects_follow_privacy(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    mail = await make_professor("prof-privacidad@frc.utn.edu.ar")
    sy = await section_year(client, admin, "3K1", 2026)
    await assign_professor(client, admin, mail, sy)
    await _enroll(client, admin, ANA_ID, sy)
    public = await _project(client, admin, sy)
    protected = await _project(client, admin, sy)
    private = await _project(client, admin, sy)
    for project, privacy, name in (
        (public, "public", "Público"),
        (protected, "protected", "Protegido"),
        (private, "private", "Privado"),
    ):
        await _set_privacy(project["id_project"], privacy, name)
        await _set_status(project["id_project"], "in_idea")

    # La alumna cursó ese año pero no es miembro de ningún grupo: no es privilegiada.
    student = (await client.get(PROJECTS, headers=await login(STUDENT))).json()
    by_id = {p["id_project"]: p for p in student["items"]}
    assert student["total"] == 2
    assert private["id_project"] not in by_id
    assert by_id[public["id_project"]]["restricted"] is False
    assert by_id[public["id_project"]]["name"] == "Público"
    assert by_id[protected["id_project"]]["restricted"] is True
    assert by_id[protected["id_project"]]["name"] is None

    # El profesor de ese curso lectivo es privilegiado: ve todo completo.
    professor = (await client.get(PROJECTS, headers=await login(mail))).json()
    assert professor["total"] == 3
    assert all(p["restricted"] is False for p in professor["items"])


# ---------- orden y paginación ----------
async def test_ordering_and_pagination(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2026)
    await _enroll(client, admin, ANA_ID, sy)
    first = await _project(client, admin, sy)
    second = await _project(client, admin, sy)
    assert second["group_number"] > first["group_number"]

    headers = await login(STUDENT)
    listing = (await client.get(PROJECTS, headers=headers)).json()
    assert [p["group_number"] for p in listing["items"]] == [
        first["group_number"],
        second["group_number"],
    ]
    page = (await client.get(PROJECTS, params={"limit": 1}, headers=headers)).json()
    assert len(page["items"]) == 1 and page["total"] == 2
    page2 = (await client.get(PROJECTS, params={"limit": 1, "offset": 1}, headers=headers)).json()
    assert len(page2["items"]) == 1
    assert (await client.get(PROJECTS, params={"limit": 0}, headers=headers)).status_code == 422


async def test_super_admin_with_assignments_gets_courses(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    mail = await make_professor("super-docente@frc.utn.edu.ar", is_super_admin=True)
    sy = await section_year(client, admin, "3K1", 2026)
    await assign_professor(client, admin, mail, sy)
    project = await _project(client, admin, sy)

    headers = await login(mail)
    body = (await client.get(URL, headers=headers)).json()
    assert [section["id_section_year"] for section in body["section_years"]] == [sy]
    listing = (await client.get(PROJECTS, headers=headers)).json()
    assert project["id_project"] in [item["id_project"] for item in listing["items"]]


async def test_student_prefers_cursada_over_group(client, login):
    admin = await login(SUPER_ADMIN)
    sy_old = await section_year(client, admin, "3K1", 2025)
    sy_new = await section_year(client, admin, "3K2", 2026)
    await _enroll(client, admin, ANA_ID, sy_old)
    project_new = await _project(client, admin, sy_new)
    joined = await client.post(
        f"/projects/{project_new['id_project']}/members",
        headers=await login(STUDENT),
    )
    assert joined.status_code == 201, joined.text

    headers = await login(STUDENT)
    body = (await client.get(URL, headers=headers)).json()
    assert [section["id_section_year"] for section in body["section_years"]] == [sy_old]
    listing = (await client.get(PROJECTS, headers=headers)).json()
    assert project_new["id_project"] not in [
        item["id_project"] for item in listing["items"]
    ]
