import re

PASSWORD = "Test1234!"
STUDENT = "100001@sistemas.frc.utn.edu.ar"
SUPER_ADMIN = "marta.rodriguez@frc.utn.edu.ar"


def get_otp(outbox: list[dict], to: str) -> str:
    for mail in reversed(outbox):
        if mail["to"] == to and "verificación" in mail["subject"]:
            return re.search(r"\b(\d{6})\b", mail["body"]).group(1)
    raise AssertionError(f"No hay código OTP enviado a {to}")


def refresh_cookie(response) -> str:
    return re.search(r"refresh_token=([^;]+)", response.headers["set-cookie"]).group(1)


async def set_password(client, outbox, mail: str, new_password: str) -> None:
    """Flujo completo: pedir código -> leerlo del 'mail' -> confirmar."""
    r = await client.post("/auth/password/request", json={"email": mail})
    assert r.status_code == 202
    r = await client.post(
        "/auth/password/confirm",
        json={"email": mail, "code": get_otp(outbox, mail), "new_password": new_password},
    )
    assert r.status_code == 204, r.text