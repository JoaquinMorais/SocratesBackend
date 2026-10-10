from config.database import SessionLocal
from models import Project, StudentProject
from tests.helpers import STUDENT, SUPER_ADMIN

LUIS = "100002@sistemas.frc.utn.edu.ar"
ANA_ID, LUIS_ID = 1, 2  # ids de los alumnos del seed
URL = "/projects"
BULK = f"{URL}/bulk"
DATA = {
    "name": "Proyecto X",
    "description": "Descripción",
    "objective": "Objetivo",
    "problem": "Problemática",
}

ENDPOINTS = [
    ("POST", URL, {"id_section_year": 1}),
    ("POST", BULK, {"id_section_year": 1, "quantity": 2}),
    ("GET", URL, None),
    ("GET", f"{URL}/1", None),
    ("DELETE", f"{URL}/1", None),
]
MANAGE = [ENDPOINTS[0], ENDPOINTS[1], ENDPOINTS[4]]


# ---------- helpers ----------
async def _section_year(client, headers, name: str = "3K1", year: int = 2025) -> int:
    r = await client.post("/sections", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    r = await client.post(
        "/section-years", json={"year": year, "id_section": r.json()["id_section"]}, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()["id_section_year"]


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


async def _create(client, headers, id_section_year: int, **extra) -> dict:
    r = await client.post(URL, json={"id_section_year": id_section_year, **extra}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def _set(id_project: int, **fields) -> None:
    async with SessionLocal() as s:
        project = await s.get(Project, id_project)
        for key, value in fields.items():
            setattr(project, key, value)
        s.add(project)
        await s.commit()


async def _add_student(id_project: int, id_student: int) -> None:
    async with SessionLocal() as s:
        s.add(StudentProject(id_student=id_student, id_project=id_project))
        await s.commit()


# ---------- permisos ----------
async def test_requires_authentication(client):
    for method, url, body in ENDPOINTS:
        r = await client.request(method, url, json=body)
        assert r.status_code == 401, (method, url)


async def test_student_cannot_create_or_delete(client, login):
    headers = await login(STUDENT)
    for method, url, body in MANAGE:
        r = await client.request(method, url, json=body, headers=headers)
        assert r.status_code == 403, (method, url)


async def test_unassigned_professor_cannot_create_or_delete(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    project = await _create(client, admin, sy)
    headers = await login(await make_professor("prof@frc.utn.edu.ar"))
    attempts = [
        ("POST", URL, {"id_section_year": sy}),
        ("POST", BULK, {"id_section_year": sy, "quantity": 2}),
        ("DELETE", f"{URL}/{project['id_project']}", None),
    ]
    for method, url, body in attempts:
        r = await client.request(method, url, json=body, headers=headers)
        assert r.status_code == 403, (method, url)


async def test_assigned_professor_manages_only_own_section_year(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    mail = await make_professor("prof@frc.utn.edu.ar")
    sy1 = await _section_year(client, admin, "3K1")
    sy2 = await _section_year(client, admin, "3K2")
    await _assign_professor(client, admin, mail, sy1)
    prof = await login(mail)

    created = await _create(client, prof, sy1)
    assert created["group_number"] == 1
    bulk = await client.post(BULK, json={"id_section_year": sy1, "quantity": 2}, headers=prof)
    assert bulk.status_code == 201

    other = await _create(client, admin, sy2)
    assert (await client.post(URL, json={"id_section_year": sy2}, headers=prof)).status_code == 403
    assert (await client.delete(f"{URL}/{other['id_project']}", headers=prof)).status_code == 403
    assert (await client.delete(f"{URL}/{created['id_project']}", headers=prof)).status_code == 204


async def test_super_admin_manages_any_section_year(client, login):
    admin = await login(SUPER_ADMIN)
    sy1 = await _section_year(client, admin, "3K1")
    sy2 = await _section_year(client, admin, "3K2", 2026)
    p1 = await _create(client, admin, sy1)
    p2 = await _create(client, admin, sy2)
    assert (await client.delete(f"{URL}/{p1['id_project']}", headers=admin)).status_code == 204
    assert (await client.delete(f"{URL}/{p2['id_project']}", headers=admin)).status_code == 204


# ---------- crear ----------
async def test_create_project_defaults(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin, "3K1", 2025)
    p = await _create(client, admin, sy)
    assert p["id_project"]
    assert (p["id_section_year"], p["year"], p["section_name"]) == (sy, 2025, "3K1")
    assert (p["group_number"], p["privacy"], p["restricted"]) == (1, "private", False)
    assert [p[k] for k in ("name", "description", "objective", "problem")] == [None] * 4


async def test_create_assigns_next_group_number(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    assert (await _create(client, admin, sy))["group_number"] == 1
    assert (await _create(client, admin, sy, group_number=5))["group_number"] == 5
    assert (await _create(client, admin, sy))["group_number"] == 6


async def test_create_duplicate_group_number_rejected(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    await _create(client, admin, sy, group_number=3)
    r = await client.post(URL, json={"id_section_year": sy, "group_number": 3}, headers=admin)
    assert r.status_code == 409


async def test_same_group_number_in_other_section_year_is_ok(client, login):
    admin = await login(SUPER_ADMIN)
    sy1 = await _section_year(client, admin, "3K1")
    sy2 = await _section_year(client, admin, "3K2")
    await _create(client, admin, sy1, group_number=1)
    await _create(client, admin, sy2, group_number=1)


async def test_create_unknown_section_year(client, login):
    r = await client.post(URL, json={"id_section_year": 999}, headers=await login(SUPER_ADMIN))
    assert r.status_code == 404


async def test_create_invalid_rejected(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    for body in (
        {},
        {"id_section_year": 0},
        {"id_section_year": sy, "group_number": 0},
        {"id_section_year": sy, "privacy": "public"},  # la privacidad inicial no se elige
        {"id_section_year": sy, "name": "X"},
    ):
        r = await client.post(URL, json=body, headers=admin)
        assert r.status_code == 422, body


# ---------- crear en masa ----------
async def test_bulk_create(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    r = await client.post(BULK, json={"id_section_year": sy, "quantity": 3}, headers=admin)
    assert r.status_code == 201
    assert [p["group_number"] for p in r.json()] == [1, 2, 3]
    assert {p["privacy"] for p in r.json()} == {"private"}
    r = await client.post(BULK, json={"id_section_year": sy, "quantity": 2}, headers=admin)
    assert [p["group_number"] for p in r.json()] == [4, 5]


async def test_bulk_continues_after_last_group_number(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    groups = (await client.post(BULK, json={"id_section_year": sy, "quantity": 3}, headers=admin)).json()
    await client.delete(f"{URL}/{groups[1]['id_project']}", headers=admin)  # queda el hueco del 2
    r = await client.post(BULK, json={"id_section_year": sy, "quantity": 1}, headers=admin)
    assert [p["group_number"] for p in r.json()] == [4]


async def test_bulk_unknown_section_year(client, login):
    r = await client.post(BULK, json={"id_section_year": 999, "quantity": 2}, headers=await login(SUPER_ADMIN))
    assert r.status_code == 404


async def test_bulk_invalid_rejected(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    for body in (
        {},
        {"id_section_year": sy},
        {"id_section_year": sy, "quantity": 0},
        {"id_section_year": sy, "quantity": 51},
        {"id_section_year": 0, "quantity": 2},
        {"id_section_year": sy, "quantity": 2, "extra": 1},
    ):
        r = await client.post(BULK, json=body, headers=admin)
        assert r.status_code == 422, body


# ---------- consultar ----------
async def test_list_sorted_and_filtered(client, login):
    admin = await login(SUPER_ADMIN)
    sy_a = await _section_year(client, admin, "3K1", 2025)
    sy_b = await _section_year(client, admin, "3K2", 2025)
    r = await client.get("/sections", params={"q": "3K1"}, headers=admin)
    sy_c = (await client.post(
        "/section-years",
        json={"year": 2024, "id_section": r.json()["items"][0]["id_section"]},
        headers=admin,
    )).json()["id_section_year"]
    await _create(client, admin, sy_b)
    await _create(client, admin, sy_a)
    await _create(client, admin, sy_a)
    await _create(client, admin, sy_c)

    body = (await client.get(URL, headers=admin)).json()
    assert body["total"] == 4
    assert [(i["year"], i["section_name"], i["group_number"]) for i in body["items"]] == [
        (2025, "3K1", 1),
        (2025, "3K1", 2),
        (2025, "3K2", 1),
        (2024, "3K1", 1),
    ]

    async def total(query: str) -> int:
        return (await client.get(f"{URL}?{query}", headers=admin)).json()["total"]

    assert await total(f"id_section_year={sy_a}") == 2
    assert await total("year=2025") == 3
    id_section = body["items"][0]["id_section"]
    assert await total(f"id_section={id_section}") == 3
    await _set(body["items"][0]["id_project"], privacy="public")
    assert await total("privacy=public") == 1
    assert await total("privacy=private") == 3
    assert (await client.get(f"{URL}?privacy=otro", headers=admin)).status_code == 422


async def test_list_pagination(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    await client.post(BULK, json={"id_section_year": sy, "quantity": 3}, headers=admin)
    page1 = (await client.get(f"{URL}?limit=2", headers=admin)).json()
    assert len(page1["items"]) == 2 and page1["total"] == 3
    page2 = (await client.get(f"{URL}?limit=2&offset=2", headers=admin)).json()
    assert len(page2["items"]) == 1
    assert (await client.get(f"{URL}?limit=0", headers=admin)).status_code == 422


async def test_get_not_found(client, login):
    assert (await client.get(f"{URL}/999", headers=await login(SUPER_ADMIN))).status_code == 404


# ---------- visibilidad según privacidad ----------
async def _project_with_data(client, admin, privacy: str) -> tuple[int, int]:
    sy = await _section_year(client, admin)
    project = await _create(client, admin, sy)
    await _set(project["id_project"], privacy=privacy, **DATA)
    return sy, project["id_project"]


def _item(listing: dict, id_project: int) -> dict:
    return next(i for i in listing["items"] if i["id_project"] == id_project)


async def _assert_detail_visible(client, headers, id_project: int) -> None:
    item = _item((await client.get(URL, headers=headers)).json(), id_project)
    assert item["restricted"] is False
    assert {k: item[k] for k in DATA} == DATA
    one = await client.get(f"{URL}/{id_project}", headers=headers)
    assert one.status_code == 200 and {k: one.json()[k] for k in DATA} == DATA


async def test_public_project_detail_visible_to_everyone(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    _, pid = await _project_with_data(client, admin, "public")
    outsider_prof = await login(await make_professor("prof@frc.utn.edu.ar"))
    for headers in (await login(LUIS), outsider_prof):
        await _assert_detail_visible(client, headers, pid)


async def test_protected_project_info_visible_to_everyone(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    _, pid = await _project_with_data(client, admin, "protected")
    outsider_prof = await login(await make_professor("prof@frc.utn.edu.ar"))
    for headers in (await login(LUIS), outsider_prof):
        await _assert_detail_visible(client, headers, pid)


async def test_private_project_detail_hidden_from_outsiders(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    _, pid = await _project_with_data(client, admin, "private")
    outsider_prof = await login(await make_professor("prof@frc.utn.edu.ar"))
    for headers in (await login(LUIS), outsider_prof):
        item = _item((await client.get(URL, headers=headers)).json(), pid)
        assert item["restricted"] is True
        assert [item[k] for k in DATA] == [None] * 4
        assert (item["group_number"], item["privacy"]) == (1, "private")  # lo básico sigue visible
        assert (await client.get(f"{URL}/{pid}", headers=headers)).status_code == 403


async def test_private_project_detail_visible_to_members_and_staff(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sy, pid = await _project_with_data(client, admin, "private")
    await _add_student(pid, ANA_ID)
    mail = await make_professor("prof@frc.utn.edu.ar")
    await _assign_professor(client, admin, mail, sy)

    for headers in (await login(STUDENT), await login(mail), admin):  # miembro, profesor del curso, super admin
        await _assert_detail_visible(client, headers, pid)
    # otro alumno que no es miembro, sigue sin acceso
    assert (await client.get(f"{URL}/{pid}", headers=await login(LUIS))).status_code == 403


# ---------- eliminar ----------
async def test_delete_empty_project(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    url = f"{URL}/{project['id_project']}"
    assert (await client.delete(url, headers=admin)).status_code == 204
    assert (await client.get(url, headers=admin)).status_code == 404
    assert (await client.get(URL, headers=admin)).json()["total"] == 0


async def test_delete_not_found(client, login):
    assert (await client.delete(f"{URL}/999", headers=await login(SUPER_ADMIN))).status_code == 404


async def test_cannot_delete_project_with_students(client, login):
    admin = await login(SUPER_ADMIN)
    project = await _create(client, admin, await _section_year(client, admin))
    await _add_student(project["id_project"], ANA_ID)
    url = f"{URL}/{project['id_project']}"
    assert (await client.delete(url, headers=admin)).status_code == 409
    assert (await client.get(url, headers=admin)).status_code == 200  # sigue existiendo


async def test_deleted_group_number_can_be_reused(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    project = await _create(client, admin, sy)
    await client.delete(f"{URL}/{project['id_project']}", headers=admin)
    assert (await _create(client, admin, sy, group_number=1))["group_number"] == 1


async def test_cannot_delete_section_year_with_projects(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    project = await _create(client, admin, sy)
    assert (await client.delete(f"/section-years/{sy}", headers=admin)).status_code == 409
    await client.delete(f"{URL}/{project['id_project']}", headers=admin)
    assert (await client.delete(f"/section-years/{sy}", headers=admin)).status_code == 204