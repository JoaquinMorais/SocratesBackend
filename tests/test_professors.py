from tests.helpers import STUDENT, SUPER_ADMIN, set_password


def professor(mail: str, **kw) -> dict:
    return {
        "first_name": "Carlos",
        "last_name": "Ruiz",
        "legajo": 200002,
        "birth_date": "1985-02-01",
        "mail": mail,
        **kw,
    }


async def test_requires_authentication(client):
    assert (await client.post("/professors", json=professor("c@frc.utn.edu.ar"))).status_code == 401


async def test_student_cannot_create_professors(client, login):
    r = await client.post(
        "/professors", json=professor("c@frc.utn.edu.ar"), headers=await login(STUDENT)
    )
    assert r.status_code == 403


async def test_regular_professor_cannot_create_professors(client, login, make_professor):
    mail = await make_professor("prof@frc.utn.edu.ar")
    r = await client.post(
        "/professors", json=professor("c@frc.utn.edu.ar"), headers=await login(mail)
    )
    assert r.status_code == 403


async def test_super_admin_creates_professor(client, login, outbox):
    r = await client.post(
        "/professors", json=professor("c.ruiz@frc.utn.edu.ar"), headers=await login(SUPER_ADMIN)
    )
    assert r.status_code == 201
    assert r.json()["email"] == "c.ruiz@frc.utn.edu.ar"
    assert r.json()["is_super_admin"] is False  # por defecto
    assert any(m["to"] == "c.ruiz@frc.utn.edu.ar" for m in outbox)


async def test_mail_is_normalized_and_unique(client, login):
    headers = await login(SUPER_ADMIN)
    r = await client.post("/professors", json=professor("C.Ruiz@frc.utn.edu.ar"), headers=headers)
    assert r.status_code == 201
    assert r.json()["email"] == "c.ruiz@frc.utn.edu.ar"
    r = await client.post("/professors", json=professor("c.ruiz@FRC.utn.edu.ar"), headers=headers)
    assert r.status_code == 409


async def test_student_domain_is_reserved(client, login):
    r = await client.post(
        "/professors",
        json=professor("200003@sistemas.frc.utn.edu.ar"),
        headers=await login(SUPER_ADMIN),
    )
    assert r.status_code == 422


async def test_invalid_mail(client, login):
    r = await client.post(
        "/professors", json=professor("no-es-un-mail"), headers=await login(SUPER_ADMIN)
    )
    assert r.status_code == 422


async def test_legajo_can_repeat(client, login):
    r = await client.post(
        "/professors",
        json=professor("c.ruiz@frc.utn.edu.ar", legajo=200001),  # mismo legajo que Marta
        headers=await login(SUPER_ADMIN),
    )
    assert r.status_code == 201


async def test_created_professor_sets_password_and_logs_in(client, login, outbox):
    await client.post(
        "/professors", json=professor("c.ruiz@frc.utn.edu.ar"), headers=await login(SUPER_ADMIN)
    )
    await set_password(client, outbox, "c.ruiz@frc.utn.edu.ar", "NuevaClave123")
    r = await client.post(
        "/auth/login", json={"email": "c.ruiz@frc.utn.edu.ar", "password": "NuevaClave123"}
    )
    assert r.status_code == 200


async def test_created_super_admin_can_create_professors(client, login, outbox):
    headers = await login(SUPER_ADMIN)
    await client.post(
        "/professors",
        json=professor("admin2@frc.utn.edu.ar", is_super_admin=True),
        headers=headers,
    )
    await set_password(client, outbox, "admin2@frc.utn.edu.ar", "NuevaClave123")
    h2 = await login("admin2@frc.utn.edu.ar", "NuevaClave123")
    r = await client.post("/professors", json=professor("otro@frc.utn.edu.ar"), headers=h2)
    assert r.status_code == 201