import pytest

from tests.helpers import PASSWORD, STUDENT, SUPER_ADMIN, get_otp, refresh_cookie, set_password


async def _login_raw(client, mail=STUDENT, password=PASSWORD):
    return await client.post("/auth/login", json={"email": mail, "password": password})


# ---------- login ----------
async def test_login_student(client):
    r = await _login_raw(client)
    assert r.status_code == 200
    assert r.json()["access_token"]
    assert "refresh_token" not in r.json()  # el refresh solo viaja por cookie
    cookie = r.headers["set-cookie"]
    assert "refresh_token=" in cookie and "HttpOnly" in cookie


async def test_login_professor(client):
    assert (await _login_raw(client, SUPER_ADMIN)).status_code == 200


@pytest.mark.parametrize(
    "mail,password",
    [
        (STUDENT, "incorrecta"),
        ("999999@sistemas.frc.utn.edu.ar", PASSWORD),
        ("100001", PASSWORD),  # el legajo suelto ya no sirve
        ("nadie@frc.utn.edu.ar", PASSWORD),
    ],
)
async def test_login_invalid(client, mail, password):
    assert (await _login_raw(client, mail, password)).status_code == 401


# ---------- me ----------
async def test_me_student(client, login):
    r = await client.get("/me", headers=await login(STUDENT))
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "student"
    assert body["email"] == STUDENT
    assert body["legajo"] == 100001
    assert "is_super_admin" not in body  # no aplica a alumnos


async def test_me_super_admin(client, login):
    r = await client.get("/me", headers=await login(SUPER_ADMIN))
    body = r.json()
    assert body["role"] == "professor"
    assert body["email"] == SUPER_ADMIN
    assert body["is_super_admin"] is True


async def test_me_requires_valid_token(client):
    assert (await client.get("/me")).status_code == 401
    r = await client.get("/me", headers={"Authorization": "Bearer basura"})
    assert r.status_code == 401


# ---------- refresh / logout ----------
async def test_refresh_rotates_token(client):
    old = refresh_cookie(await _login_raw(client))
    r = await client.post("/auth/refresh")
    assert r.status_code == 200
    assert r.json()["access_token"]
    assert refresh_cookie(r) != old


async def test_refresh_rejects_used_token(client):
    old = refresh_cookie(await _login_raw(client))
    await client.post("/auth/refresh")  # rota: el viejo queda inválido
    r = await client.post("/auth/refresh", headers={"Cookie": f"refresh_token={old}"})
    assert r.status_code == 401


async def test_refresh_without_cookie(client):
    assert (await client.post("/auth/refresh")).status_code == 401


async def test_logout_revokes_refresh_token(client):
    old = refresh_cookie(await _login_raw(client))
    assert (await client.post("/auth/logout")).status_code == 204
    r = await client.post("/auth/refresh", headers={"Cookie": f"refresh_token={old}"})
    assert r.status_code == 401


async def test_logout_without_cookie_is_ok(client):
    assert (await client.post("/auth/logout")).status_code == 204


# ---------- contraseña por OTP ----------
async def test_password_request_unknown_user_is_silent(client, outbox):
    r = await client.post("/auth/password/request", json={"email": "999999@sistemas.frc.utn.edu.ar"})
    assert r.status_code == 202  # misma respuesta que si existiera
    assert outbox == []


async def test_password_flow(client, outbox):
    await set_password(client, outbox, STUDENT, "NuevaClave123")
    assert (await _login_raw(client, STUDENT, "NuevaClave123")).status_code == 200
    assert (await _login_raw(client, STUDENT, PASSWORD)).status_code == 401


async def test_otp_is_single_use(client, outbox):
    await client.post("/auth/password/request", json={"email": STUDENT})
    code = get_otp(outbox, STUDENT)
    body = {"email": STUDENT, "code": code, "new_password": "NuevaClave123"}
    assert (await client.post("/auth/password/confirm", json=body)).status_code == 204
    assert (await client.post("/auth/password/confirm", json=body)).status_code == 400


async def test_otp_blocked_after_too_many_attempts(client, outbox):
    await client.post("/auth/password/request", json={"email": STUDENT})
    real = get_otp(outbox, STUDENT)
    wrong = "999999" if real != "999999" else "000000"
    for _ in range(5):
        r = await client.post(
            "/auth/password/confirm",
            json={"email": STUDENT, "code": wrong, "new_password": "NuevaClave123"},
        )
        assert r.status_code == 400
    r = await client.post(
        "/auth/password/confirm",
        json={"email": STUDENT, "code": real, "new_password": "NuevaClave123"},
    )
    assert r.status_code == 400  # el código correcto ya no sirve


async def test_password_too_short(client, outbox):
    await client.post("/auth/password/request", json={"email": STUDENT})
    r = await client.post(
        "/auth/password/confirm",
        json={"email": STUDENT, "code": get_otp(outbox, STUDENT), "new_password": "corta"},
    )
    assert r.status_code == 422


async def test_password_change_closes_sessions(client, outbox):
    old = refresh_cookie(await _login_raw(client))
    await set_password(client, outbox, STUDENT, "NuevaClave123")
    r = await client.post("/auth/refresh", headers={"Cookie": f"refresh_token={old}"})
    assert r.status_code == 401