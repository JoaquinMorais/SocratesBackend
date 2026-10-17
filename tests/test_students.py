from config.database import SessionLocal
from models import Project, StudentProject
from tests.helpers import PASSWORD, STUDENT, SUPER_ADMIN, set_password
from utils.statuses import INITIAL_STATUS, get_status

URL = "/students"
ANA_ID, LUIS_ID = 1, 2  # ids de los alumnos del seed


def student(legajo: int, **kw) -> dict:
    return {
        "first_name": "Sofía",
        "last_name": "Díaz",
        "legajo": legajo,
        "birth_date": "2003-05-10",
        "enrollment_year": 2023,
        **kw,
    }


# ---------- helpers de grupos ----------
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


async def _assign_professor(client, admin, mail: str, id_section_year: int) -> None:
    r = await client.get("/users", params={"q": mail}, headers=admin)
    id_professor = r.json()["items"][0]["id_user"]
    r = await client.post(
        "/professor-section-years",
        json={"id_professor": id_professor, "id_section_year": id_section_year},
        headers=admin,
    )
    assert r.status_code == 201, r.text


async def _create_project(client, headers, id_section_year: int, name: str | None = None) -> dict:
    r = await client.post("/projects", json={"id_section_year": id_section_year}, headers=headers)
    assert r.status_code == 201, r.text
    project = r.json()
    if name is not None:
        async with SessionLocal() as s:
            p = await s.get(Project, project["id_project"])
            p.name = name
            s.add(p)
            await s.commit()
    return project


async def _add_student(id_project: int, id_student: int) -> None:
    async with SessionLocal() as s:
        status = await get_status(s, "student_project", INITIAL_STATUS["student_project"])
        s.add(
            StudentProject(
                id_student=id_student, id_project=id_project, id_status=status.id_status
            )
        )
        await s.commit()


def _find(listing: dict, id_student: int) -> dict:
    return next(i for i in listing["items"] if i["id_student"] == id_student)


async def test_requires_authentication(client):
    assert (await client.post("/students", json=student(100010))).status_code == 401


async def test_student_cannot_create_students(client, login):
    r = await client.post("/students", json=student(100010), headers=await login(STUDENT))
    assert r.status_code == 403


async def test_professor_creates_student(client, login, make_professor, outbox):
    mail = await make_professor("prof@frc.utn.edu.ar")  # profesor común, no super admin
    r = await client.post("/students", json=student(100010), headers=await login(mail))
    assert r.status_code == 201
    assert r.json()["email"] == "100010@sistemas.frc.utn.edu.ar"
    assert any(m["to"] == r.json()["email"] for m in outbox)  # mail de bienvenida


async def test_created_student_can_set_password_and_login(client, login, outbox):
    headers = await login(SUPER_ADMIN)
    mail = (await client.post("/students", json=student(100010), headers=headers)).json()["email"]
    r = await client.post("/auth/login", json={"email": mail, "password": "NuevaClave123"})
    assert r.status_code == 401  # todavía no tiene contraseña
    await set_password(client, outbox, mail, "NuevaClave123")
    r = await client.post("/auth/login", json={"email": mail, "password": "NuevaClave123"})
    assert r.status_code == 200


async def test_duplicate_legajo_rejected(client, login):
    r = await client.post("/students", json=student(100001), headers=await login(SUPER_ADMIN))
    assert r.status_code == 422
    assert r.json()["detail"][0]["legajo"] == 100001


async def test_bulk_create(client, login):
    r = await client.post(
        "/students/bulk",
        json={"students": [student(100010), student(100011), student(100012)]},
        headers=await login(SUPER_ADMIN),
    )
    assert r.status_code == 201
    assert len(r.json()) == 3


async def test_bulk_is_all_or_nothing(client, login):
    headers = await login(SUPER_ADMIN)
    r = await client.post(
        "/students/bulk",
        json={"students": [student(100010), student(100001)]},  # la 2da ya existe
        headers=headers,
    )
    assert r.status_code == 422
    assert [e["row"] for e in r.json()["detail"]] == [2]
    # la primera no se creó: se puede cargar sin error
    assert (await client.post("/students", json=student(100010), headers=headers)).status_code == 201


async def test_bulk_duplicate_inside_request(client, login):
    r = await client.post(
        "/students/bulk",
        json={"students": [student(100010), student(100010)]},
        headers=await login(SUPER_ADMIN),
    )
    assert r.status_code == 422
    assert r.json()["detail"][0]["row"] == 2


async def test_invalid_student_data(client, login):
    r = await client.post(
        "/students", json=student(100010, enrollment_year=1800), headers=await login(SUPER_ADMIN)
    )
    assert r.status_code == 422


# ---------- GET /students (consultar) ----------
async def test_list_requires_authentication(client):
    assert (await client.get(URL)).status_code == 401


async def test_student_cannot_list_students(client, login):
    r = await client.get(URL, headers=await login(STUDENT))
    assert r.status_code == 403


async def test_super_admin_lists_all_students(client, login):
    r = await client.get(URL, headers=await login(SUPER_ADMIN))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert [i["legajo"] for i in body["items"]] == [100001, 100002]
    assert all(i["groups"] == [] for i in body["items"])  # todavía sin grupos


async def test_unassigned_professor_sees_no_students(client, login, make_professor):
    headers = await login(await make_professor("prof@frc.utn.edu.ar"))
    body = (await client.get(URL, headers=headers)).json()
    assert body["total"] == 0 and body["items"] == []


async def test_professor_sees_only_own_section_year(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    mail = await make_professor("prof@frc.utn.edu.ar")
    sy1 = await _section_year(client, admin, "3K1")
    sy2 = await _section_year(client, admin, "3K2")
    await _assign_professor(client, admin, mail, sy1)
    p1 = await _create_project(client, admin, sy1, name="Grupo de Ana")
    p2 = await _create_project(client, admin, sy2)
    await _add_student(p1["id_project"], ANA_ID)
    await _add_student(p2["id_project"], LUIS_ID)

    body = (await client.get(URL, headers=await login(mail))).json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["id_student"] == ANA_ID
    assert len(item["groups"]) == 1
    group = item["groups"][0]
    assert (group["id_project"], group["project_name"], group["group_number"]) == (
        p1["id_project"], "Grupo de Ana", 1,
    )


async def test_groups_list_all_memberships(client, login):
    admin = await login(SUPER_ADMIN)
    sy_2025 = await _section_year(client, admin, "3K1", 2025)
    sy_2024 = await _section_year(client, admin, "3K2", 2024)
    p25 = await _create_project(client, admin, sy_2025, name="Actual")
    p24 = await _create_project(client, admin, sy_2024, name="Anterior")
    await _add_student(p25["id_project"], ANA_ID)
    await _add_student(p24["id_project"], ANA_ID)

    body = (await client.get(URL, headers=admin)).json()
    ana = _find(body, ANA_ID)
    assert [g["year"] for g in ana["groups"]] == [2025, 2024]  # más reciente primero
    assert [g["project_name"] for g in ana["groups"]] == ["Actual", "Anterior"]
    assert _find(body, LUIS_ID)["groups"] == []


async def test_list_filters(client, login):
    admin = await login(SUPER_ADMIN)
    sy1 = await _section_year(client, admin, "3K1", 2025)
    sy2 = await _section_year(client, admin, "3K2", 2026)
    p1 = await _create_project(client, admin, sy1)
    p2 = await _create_project(client, admin, sy2)
    await _add_student(p1["id_project"], ANA_ID)
    await _add_student(p2["id_project"], LUIS_ID)

    async def total(query: str) -> int:
        return (await client.get(f"{URL}?{query}", headers=admin)).json()["total"]

    assert await total(f"id_section_year={sy1}") == 1
    assert await total("year=2025") == 1
    assert await total("year=2026") == 1
    assert await total(f"id_section={p1['id_section']}") == 1
    assert await total(f"id_section_year={sy1}&year=2026") == 0  # combinación vacía


async def test_list_search(client, login):
    admin = await login(SUPER_ADMIN)

    async def total(params: dict) -> int:
        return (await client.get(URL, params=params, headers=admin)).json()["total"]

    assert await total({"q": "Ana"}) == 1
    assert await total({"q": "Gómez"}) == 1
    assert await total({"q": "100002"}) == 1
    assert await total({"q": "Nadie"}) == 0


async def test_professor_cannot_filter_foreign_section_year(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sy1 = await _section_year(client, admin, "3K1")
    sy2 = await _section_year(client, admin, "3K2")
    mail = await make_professor("prof@frc.utn.edu.ar")
    await _assign_professor(client, admin, mail, sy1)
    headers = await login(mail)
    assert (await client.get(f"{URL}?id_section_year={sy1}", headers=headers)).status_code == 200
    assert (await client.get(f"{URL}?id_section_year={sy2}", headers=headers)).status_code == 403


async def test_list_does_not_expose_private_data(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin)
    project = await _create_project(client, admin, sy, name="Grupo 1")
    await _add_student(project["id_project"], ANA_ID)

    body = (await client.get(URL, headers=admin)).json()
    ana = _find(body, ANA_ID)
    assert "birth_date" not in ana
    assert set(ana["groups"][0]) == {
        "id_project", "project_name", "group_number",
        "id_section_year", "year", "id_section", "section_name",
    }


async def test_list_pagination(client, login):
    admin = await login(SUPER_ADMIN)
    page1 = (await client.get(f"{URL}?limit=1", headers=admin)).json()
    assert len(page1["items"]) == 1 and page1["total"] == 2
    page2 = (await client.get(f"{URL}?limit=1&offset=1", headers=admin)).json()
    assert len(page2["items"]) == 1
    assert (await client.get(f"{URL}?limit=0", headers=admin)).status_code == 422


# ---------- PATCH /students/{id} ----------
async def test_patch_requires_authentication(client):
    assert (await client.patch("/students/1", json={"first_name": "X"})).status_code == 401


async def test_student_cannot_patch_students(client, login):
    r = await client.patch("/students/2", json={"first_name": "X"}, headers=await login(STUDENT))
    assert r.status_code == 403


async def test_professor_edits_student(client, login, make_professor):
    mail = await make_professor("prof@frc.utn.edu.ar")
    r = await client.patch(
        "/students/1",
        json={"first_name": "Anita", "birth_date": "2001-02-03", "enrollment_year": 2020},
        headers=await login(mail),
    )
    assert r.status_code == 200
    body = r.json()
    assert (body["first_name"], body["last_name"], body["enrollment_year"]) == ("Anita", "Gómez", 2020)


async def test_legajo_change_updates_login_mail(client, login):
    r = await client.patch("/students/1", json={"legajo": 100050}, headers=await login(SUPER_ADMIN))
    assert r.status_code == 200
    assert r.json()["email"] == "100050@sistemas.frc.utn.edu.ar"
    new = await client.post(
        "/auth/login", json={"email": "100050@sistemas.frc.utn.edu.ar", "password": PASSWORD}
    )
    assert new.status_code == 200  # conserva su contraseña
    old = await client.post("/auth/login", json={"email": STUDENT, "password": PASSWORD})
    assert old.status_code == 401


async def test_patch_duplicate_legajo_rejected(client, login):
    r = await client.patch("/students/1", json={"legajo": 100002}, headers=await login(SUPER_ADMIN))
    assert r.status_code == 409


async def test_patch_same_legajo_is_ok(client, login):
    r = await client.patch("/students/1", json={"legajo": 100001}, headers=await login(SUPER_ADMIN))
    assert r.status_code == 200


async def test_student_legajo_may_match_a_professor(client, login):
    r = await client.patch("/students/1", json={"legajo": 200001}, headers=await login(SUPER_ADMIN))
    assert r.status_code == 200  # 200001 es el legajo de Marta (profesora)


async def test_patch_student_not_found(client, login):
    r = await client.patch("/students/999", json={"first_name": "X"}, headers=await login(SUPER_ADMIN))
    assert r.status_code == 404


async def test_patch_student_forbidden_fields(client, login):
    headers = await login(SUPER_ADMIN)
    for field, value in [("email", "x@x.com"), ("is_super_admin", True), ("password", "Abcdefgh1")]:
        r = await client.patch("/students/1", json={field: value}, headers=headers)
        assert r.status_code == 422, field


async def test_patch_student_empty_body_rejected(client, login):
    r = await client.patch("/students/1", json={}, headers=await login(SUPER_ADMIN))
    assert r.status_code == 422


async def test_patch_student_invalid_values_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    assert (await client.patch("/students/1", json={"enrollment_year": 1800}, headers=headers)).status_code == 422
    assert (await client.patch("/students/1", json={"legajo": 0}, headers=headers)).status_code == 422