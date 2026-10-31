import re

from sqlmodel import select

import config.database as database
from models import SectionYear, StudentSectionYear
from models.student_section_year import ATTENDING

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

async def section_year(
    client, headers: dict, name: str = "3K1", year: int = 2025
) -> int:
    """Crea una comisión y su curso lectivo; devuelve el id del curso."""
    r = await client.post("/sections", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    r = await client.post(
        "/section-years",
        json={
            "year": year,
            "id_section": r.json()["id_section"],
            "min_students": 1,
            "max_students": 10,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id_section_year"]


async def assign_professor(
    client, admin_headers: dict, mail: str, id_section_year: int
) -> None:
    """Asigna a un profesor (buscado por mail) al curso lectivo."""
    r = await client.get("/users", params={"q": mail}, headers=admin_headers)
    id_professor = r.json()["items"][0]["id_user"]
    r = await client.post(
        "/professor-section-years",
        json={"id_professor": id_professor, "id_section_year": id_section_year},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text


async def create_cursada(
    id_student: int, id_section_year: int, state: str = ATTENDING
) -> StudentSectionYear:
    """Prepara una cursada directo en la BD (atajo de tests, sin pasar por grupos)."""
    async with database.SessionLocal() as session:
        existing = (
            await session.exec(
                select(StudentSectionYear).where(
                    StudentSectionYear.id_student == id_student,
                    StudentSectionYear.id_section_year == id_section_year,
                    StudentSectionYear.state != "registered",
                )
            )
        ).first()
        if existing is not None:
            if existing.state != state:
                existing.state = state
                session.add(existing)
                await session.commit()
                await session.refresh(existing)
            return existing

        sy = await session.get(SectionYear, id_section_year)
        row = StudentSectionYear(
            id_student=id_student,
            id_section_year=id_section_year,
            year=sy.year,
            state=state,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row
