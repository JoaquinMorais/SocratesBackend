from tests.helpers import PASSWORD, STUDENT, SUPER_ADMIN, set_password

def student(legajo: int, **kw) -> dict:
    return {
        "first_name": "Sofía",
        "last_name": "Díaz",
        "legajo": legajo,
        "birth_date": "2003-05-10",
        "enrollment_year": 2023,
        **kw,
    }


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