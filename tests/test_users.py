from datetime import date

from tests.helpers import (
    PASSWORD,
    STUDENT,
    SUPER_ADMIN,
    assign_professor,
    refresh_cookie,
    section_year,
)


def _birth_date_for_age(age: int) -> str:
    """Fecha de nacimiento para cumplir exactamente `age` años hoy."""
    today = date.today()
    try:
        born = date(today.year - age, today.month, today.day)
    except ValueError:  # 29 de febrero en un año no bisiesto
        born = date(today.year - age, today.month, 28)
    return born.isoformat()


# ---------- PATCH /me ----------
async def test_update_requires_authentication(client):
    assert (await client.patch("/me", json={"first_name": "X"})).status_code == 401


async def test_student_updates_own_data(client, login):
    headers = await login(STUDENT)
    r = await client.patch(
        "/me",
        json={"first_name": "Anita", "birth_date": "2001-01-31"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["first_name"] == "Anita"
    assert r.json()["last_name"] == "Gómez"  # lo no enviado no cambia
    assert "is_super_admin" not in r.json()
    me = await client.get("/me", headers=headers)
    assert me.json()["first_name"] == "Anita"


async def test_professor_updates_own_data(client, login):
    headers = await login(SUPER_ADMIN)
    r = await client.patch("/me", json={"last_name": "Nueva"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["last_name"] == "Nueva"
    assert r.json()["is_super_admin"] is True


async def test_cannot_update_forbidden_fields(client, login):
    headers = await login(STUDENT)
    for field, value in [("legajo", 999), ("is_super_admin", True), ("email", "x@x.com"), ("enrollment_year", 2000)]:
        r = await client.patch("/me", json={field: value}, headers=headers)
        assert r.status_code == 422, field


async def test_update_empty_body_rejected(client, login):
    r = await client.patch("/me", json={}, headers=await login(STUDENT))
    assert r.status_code == 422


async def test_update_invalid_values_rejected(client, login):
    headers = await login(STUDENT)
    assert (await client.patch("/me", json={"first_name": ""}, headers=headers)).status_code == 422
    r = await client.patch("/me", json={"birth_date": "2999-01-01"}, headers=headers)
    assert r.status_code == 422


async def test_cannot_set_under_18_birth_date(client, login):
    headers = await login(STUDENT)
    r = await client.patch("/me", json={"birth_date": _birth_date_for_age(17)}, headers=headers)
    assert r.status_code == 422


# ---------- GET /users ----------
async def test_list_requires_authentication(client):
    assert (await client.get("/users")).status_code == 401


async def test_student_cannot_list_users(client, login):
    assert (await client.get("/users", headers=await login(STUDENT))).status_code == 403


async def test_regular_professor_cannot_list_users(client, login, make_professor):
    mail = await make_professor("prof@frc.utn.edu.ar")
    assert (await client.get("/users", headers=await login(mail))).status_code == 403


async def test_super_admin_lists_users(client, login):
    r = await client.get("/users", headers=await login(SUPER_ADMIN))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    # orden por apellido: Gómez, Pérez, Rodríguez
    assert [u["last_name"] for u in body["items"]] == ["Gómez", "Pérez", "Rodríguez"]


async def test_list_exposes_only_public_data(client, login):
    items = (await client.get("/users", headers=await login(SUPER_ADMIN))).json()["items"]
    for item in items:
        assert "password_hash" not in item
        assert "password" not in item
    student = next(u for u in items if u["role"] == "student")
    professor = next(u for u in items if u["role"] == "professor")
    assert "is_super_admin" not in student and student["enrollment_year"]
    assert "age" in student and isinstance(student["age"], int)
    assert "birth_date" in student
    assert professor["is_super_admin"] is True and "enrollment_year" not in professor
    assert "age" in professor and "birth_date" in professor


async def test_list_filter_by_role(client, login):
    headers = await login(SUPER_ADMIN)
    students = (await client.get("/users?role=student", headers=headers)).json()
    assert students["total"] == 2
    professors = (await client.get("/users?role=professor", headers=headers)).json()
    assert professors["total"] == 1
    assert (await client.get("/users?role=otro", headers=headers)).status_code == 422


async def test_list_search(client, login):
    headers = await login(SUPER_ADMIN)
    by_name = (await client.get("/users?q=ana", headers=headers)).json()
    assert [u["first_name"] for u in by_name["items"]] == ["Ana"]
    by_legajo = (await client.get("/users?q=100002", headers=headers)).json()
    assert [u["first_name"] for u in by_legajo["items"]] == ["Luis"]
    by_mail = (await client.get("/users?q=marta.rod", headers=headers)).json()
    assert [u["first_name"] for u in by_mail["items"]] == ["Marta"]
    assert (await client.get("/users?q=zzzz", headers=headers)).json()["total"] == 0


async def test_list_pagination(client, login):
    headers = await login(SUPER_ADMIN)
    page1 = (await client.get("/users?limit=2", headers=headers)).json()
    assert len(page1["items"]) == 2 and page1["total"] == 3
    page2 = (await client.get("/users?limit=2&offset=2", headers=headers)).json()
    assert len(page2["items"]) == 1
    assert (await client.get("/users?limit=0", headers=headers)).status_code == 422

# ---------- DELETE /users/{id} (eliminar alta errónea) ----------
LUIS = "100002@sistemas.frc.utn.edu.ar"


def _professor_payload(mail: str) -> dict:
    return {
        "first_name": "Elena",
        "last_name": "Sosa",
        "legajo": 200002,
        "birth_date": "1985-02-01",
        "mail": mail,
    }


async def _id_by_mail(client, headers, mail: str) -> int:
    r = await client.get("/users", params={"q": mail}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["items"][0]["id_user"]


async def test_delete_requires_authentication(client):
    assert (await client.delete("/users/1")).status_code == 401


async def test_student_cannot_delete_users(client, login):
    assert (await client.delete("/users/1", headers=await login(STUDENT))).status_code == 403


async def test_regular_professor_cannot_delete_users(client, login, make_professor):
    mail = await make_professor("prof-del-users@frc.utn.edu.ar")
    assert (await client.delete("/users/1", headers=await login(mail))).status_code == 403


async def test_super_admin_deletes_student_user(client, login):
    headers = await login(SUPER_ADMIN)
    r = await client.delete("/users/1", headers=headers)  # Ana, sin membresías
    assert r.status_code == 204, r.text
    r = await client.post("/auth/login", json={"email": STUDENT, "password": PASSWORD})
    assert r.status_code == 401  # el usuario ya no existe


async def test_delete_student_with_current_membership_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    sy = await section_year(client, headers)
    project = (
        await client.post("/projects", json={"id_section_year": sy}, headers=headers)
    ).json()
    r = await client.post(
        f"/projects/{project['id_project']}/members", headers=await login(LUIS)
    )
    assert r.status_code == 201, r.text  # queda `active` como jefe
    assert (await client.delete("/users/2", headers=headers)).status_code == 409


async def test_super_admin_deletes_professor_user(client, login, make_professor):
    mail = await make_professor("prof-borrar@frc.utn.edu.ar")
    headers = await login(SUPER_ADMIN)
    id_professor = await _id_by_mail(client, headers, mail)
    assert (await client.delete(f"/users/{id_professor}", headers=headers)).status_code == 204
    r = await client.post("/auth/login", json={"email": mail, "password": PASSWORD})
    assert r.status_code == 401  # el profesor ya no existe


async def test_delete_professor_with_assignment_rejected(client, login, make_professor):
    mail = await make_professor("prof-asignado@frc.utn.edu.ar")
    headers = await login(SUPER_ADMIN)
    sy = await section_year(client, headers)
    await assign_professor(client, headers, mail, sy)
    id_professor = await _id_by_mail(client, headers, mail)
    assert (await client.delete(f"/users/{id_professor}", headers=headers)).status_code == 409
    # la asignación sigue existiendo
    r = await client.get("/professor-section-years", headers=headers)
    assert r.status_code == 200
    assert any(item["id_professor"] == id_professor for item in r.json()["items"])


async def test_delete_super_admin_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    # Marta es super admin: no se puede borrar a sí misma
    assert (await client.delete("/users/3", headers=headers)).status_code == 409
    # ni a otro super admin: primero hay que quitarle el rol
    created = (
        await client.post(
            "/professors",
            json={**_professor_payload("otro-admin@frc.utn.edu.ar"), "is_super_admin": True},
            headers=headers,
        )
    ).json()
    assert (await client.delete(f"/users/{created['id_professor']}", headers=headers)).status_code == 409


async def test_delete_user_not_found(client, login):
    assert (await client.delete("/users/999", headers=await login(SUPER_ADMIN))).status_code == 404


async def test_delete_frees_mail_and_legajo(client, login):
    headers = await login(SUPER_ADMIN)
    created = (
        await client.post(
            "/professors", json=_professor_payload("recargar@frc.utn.edu.ar"), headers=headers
        )
    ).json()
    assert (await client.delete(f"/users/{created['id_professor']}", headers=headers)).status_code == 204
    r = await client.post(
        "/professors", json=_professor_payload("recargar@frc.utn.edu.ar"), headers=headers
    )
    assert r.status_code == 201, r.text  # mail y legajo quedaron libres


async def test_delete_professor_removes_sessions_and_otp(client, login, make_professor):
    mail = await make_professor("prof-sesion@frc.utn.edu.ar")
    headers = await login(SUPER_ADMIN)
    r = await client.post("/auth/login", json={"email": mail, "password": PASSWORD})
    assert r.status_code == 200, r.text
    cookie = refresh_cookie(r)
    assert (await client.post("/auth/password/request", json={"email": mail})).status_code == 202
    id_professor = await _id_by_mail(client, headers, mail)
    assert (await client.delete(f"/users/{id_professor}", headers=headers)).status_code == 204
    r = await client.post("/auth/refresh", headers={"Cookie": f"refresh_token={cookie}"})
    assert r.status_code == 401  # la sesión quedó invalidada con el usuario
