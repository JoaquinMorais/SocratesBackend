from tests.helpers import STUDENT, SUPER_ADMIN


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
        assert "birth_date" not in item
    student = next(u for u in items if u["role"] == "student")
    professor = next(u for u in items if u["role"] == "professor")
    assert "is_super_admin" not in student and student["enrollment_year"]
    assert professor["is_super_admin"] is True and "enrollment_year" not in professor


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