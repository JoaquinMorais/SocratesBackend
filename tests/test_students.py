from tests.helpers import STUDENT, SUPER_ADMIN, set_password


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