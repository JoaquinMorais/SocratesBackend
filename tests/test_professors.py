from tests.helpers import PASSWORD, STUDENT, SUPER_ADMIN, set_password

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


# ---------- PATCH /professors/{id} ----------
async def _id_of(client, headers, q: str) -> int:
    r = await client.get("/users", params={"q": q}, headers=headers)
    return r.json()["items"][0]["id_user"]


async def test_patch_requires_authentication(client):
    assert (await client.patch("/professors/3", json={"first_name": "X"})).status_code == 401


async def test_student_cannot_patch_professors(client, login):
    r = await client.patch("/professors/3", json={"first_name": "X"}, headers=await login(STUDENT))
    assert r.status_code == 403


async def test_regular_professor_cannot_patch_professors(client, login, make_professor):
    mail = await make_professor("prof@frc.utn.edu.ar")
    r = await client.patch("/professors/3", json={"first_name": "X"}, headers=await login(mail))
    assert r.status_code == 403


async def test_super_admin_edits_professor(client, login, make_professor):
    await make_professor("prof@frc.utn.edu.ar")
    admin = await login(SUPER_ADMIN)
    pid = await _id_of(client, admin, "prof@frc")
    r = await client.patch(
        f"/professors/{pid}",
        json={"first_name": "Nuevo", "legajo": 300001, "mail": "Nuevo@FRC.utn.edu.ar"},
        headers=admin,
    )
    assert r.status_code == 200
    body = r.json()
    assert (body["first_name"], body["legajo"], body["email"]) == ("Nuevo", 300001, "nuevo@frc.utn.edu.ar")


async def test_mail_change_closes_sessions_and_keeps_password(client, login, make_professor):
    await make_professor("prof@frc.utn.edu.ar")
    admin = await login(SUPER_ADMIN)
    pid = await _id_of(client, admin, "prof@frc")
    await login("prof@frc.utn.edu.ar")  # la cookie de refresh del profesor queda en el client
    r = await client.patch(f"/professors/{pid}", json={"mail": "nuevo@frc.utn.edu.ar"}, headers=admin)
    assert r.status_code == 200
    assert (await client.post("/auth/refresh")).status_code == 401  # sesión cerrada
    new = await client.post("/auth/login", json={"email": "nuevo@frc.utn.edu.ar", "password": PASSWORD})
    assert new.status_code == 200  # conserva su contraseña
    old = await client.post("/auth/login", json={"email": "prof@frc.utn.edu.ar", "password": PASSWORD})
    assert old.status_code == 401


async def test_patch_duplicate_mail_rejected(client, login, make_professor):
    await make_professor("prof@frc.utn.edu.ar")
    admin = await login(SUPER_ADMIN)
    pid = await _id_of(client, admin, "prof@frc")
    r = await client.patch(
        f"/professors/{pid}", json={"mail": "MARTA.RODRIGUEZ@frc.utn.edu.ar"}, headers=admin
    )
    assert r.status_code == 409


async def test_patch_student_domain_is_reserved(client, login):
    r = await client.patch(
        "/professors/3", json={"mail": "x@sistemas.frc.utn.edu.ar"}, headers=await login(SUPER_ADMIN)
    )
    assert r.status_code == 422


async def test_promote_and_demote_other_professor(client, login, make_professor):
    await make_professor("prof@frc.utn.edu.ar")
    admin = await login(SUPER_ADMIN)
    pid = await _id_of(client, admin, "prof@frc")
    r = await client.patch(f"/professors/{pid}", json={"is_super_admin": True}, headers=admin)
    assert r.json()["is_super_admin"] is True
    r = await client.patch(f"/professors/{pid}", json={"is_super_admin": False}, headers=admin)
    assert r.status_code == 200 and r.json()["is_super_admin"] is False


async def test_cannot_remove_own_super_admin(client, login):
    r = await client.patch(
        "/professors/3", json={"is_super_admin": False}, headers=await login(SUPER_ADMIN)
    )
    assert r.status_code == 409


async def test_super_admin_edits_self(client, login):
    r = await client.patch("/professors/3", json={"last_name": "Nueva"}, headers=await login(SUPER_ADMIN))
    assert r.status_code == 200
    assert r.json()["last_name"] == "Nueva" and r.json()["is_super_admin"] is True


async def test_patch_professor_not_found(client, login):
    r = await client.patch("/professors/999", json={"first_name": "X"}, headers=await login(SUPER_ADMIN))
    assert r.status_code == 404


async def test_patch_professor_forbidden_fields(client, login):
    headers = await login(SUPER_ADMIN)
    for field, value in [("password", "Abcdefgh1"), ("id_professor", 5), ("email", "x@frc.utn.edu.ar")]:
        r = await client.patch("/professors/3", json={field: value}, headers=headers)
        assert r.status_code == 422, field


async def test_patch_professor_empty_body_rejected(client, login):
    r = await client.patch("/professors/3", json={}, headers=await login(SUPER_ADMIN))
    assert r.status_code == 422