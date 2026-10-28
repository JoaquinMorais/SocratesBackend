from datetime import datetime, timedelta, timezone

from sqlmodel import select

from config.database import SessionLocal
from models import AttendanceSession
from tests.helpers import STUDENT, SUPER_ADMIN, assign_professor, section_year

URL = "/calendar-classes"
ANA_ID = 1
LUIS = "100002@sistemas.frc.utn.edu.ar"


def _class_body(**overrides) -> dict:
    return {
        "date": "2026-03-03",
        "start_time": "18:30",
        "end_time": "22:00",
        "modality": "in_person",
        **overrides,
    }


async def _sy(client, headers, name: str = "3K1", year: int = 2026) -> int:
    return await section_year(client, headers, name, year)


async def _class(client, headers, id_section_year: int, **overrides) -> dict:
    r = await client.post(
        f"/section-years/{id_section_year}/calendar-classes",
        json=_class_body(**overrides),
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _enroll(client, headers, id_student: int, id_section_year: int) -> dict:
    r = await client.post(
        "/student-section-years",
        json={"id_student": id_student, "id_section_year": id_section_year},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _open(client, headers, id_calendar_class: int) -> dict:
    r = await client.post(
        f"{URL}/{id_calendar_class}/attendance/open", headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _checkin(client, headers, id_calendar_class: int, code: str):
    return await client.post(
        f"{URL}/{id_calendar_class}/attendance/check-in",
        json={"code": code},
        headers=headers,
    )


async def _list(client, headers, id_calendar_class: int):
    return await client.get(f"{URL}/{id_calendar_class}/attendance", headers=headers)


# ---------- permisos ----------
async def test_requires_authentication(client):
    assert (await client.post(f"{URL}/1/attendance/open")).status_code == 401
    assert (await client.post(f"{URL}/1/attendance/close")).status_code == 401
    assert (
        await client.post(f"{URL}/1/attendance/check-in", json={"code": "123456"})
    ).status_code == 401
    assert (await client.get(f"{URL}/1/attendance")).status_code == 401
    assert (await client.post(f"{URL}/1/attendance/students/1")).status_code == 401
    assert (await client.delete(f"{URL}/1/attendance/students/1")).status_code == 401
    assert (await client.get("/me/attendance")).status_code == 401


async def test_student_cannot_manage_attendance(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    headers = await login(STUDENT)

    assert (
        await client.post(
            f"{URL}/{calendar_class['id_calendar_class']}/attendance/open",
            headers=headers,
        )
    ).status_code == 403
    assert (
        await client.post(
            f"{URL}/{calendar_class['id_calendar_class']}/attendance/close",
            headers=headers,
        )
    ).status_code == 403
    assert (
        await _list(client, headers, calendar_class["id_calendar_class"])
    ).status_code == 403
    assert (
        await client.post(
            f"{URL}/{calendar_class['id_calendar_class']}/attendance/students/1",
            headers=headers,
        )
    ).status_code == 403


async def test_assigned_professor_manages_and_other_cannot(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    enrollment = await _enroll(client, admin, ANA_ID, sy)
    assigned = await make_professor("prof-asistencia@frc.utn.edu.ar")
    other = await make_professor("prof-asist-otro@frc.utn.edu.ar", legajo=300001)
    await assign_professor(client, admin, assigned, sy)

    assigned_headers = await login(assigned)
    opened = await _open(client, assigned_headers, calendar_class["id_calendar_class"])
    assert (
        await _list(client, assigned_headers, calendar_class["id_calendar_class"])
    ).status_code == 200
    assert (
        await client.post(
            f"{URL}/{calendar_class['id_calendar_class']}/attendance/students/{enrollment['id_student_section_year']}",
            headers=assigned_headers,
        )
    ).status_code == 200
    assert (
        await client.post(
            f"{URL}/{calendar_class['id_calendar_class']}/attendance/close",
            headers=assigned_headers,
        )
    ).status_code == 204
    assert opened["code"].isdigit()

    other_headers = await login(other)
    assert (
        await client.post(
            f"{URL}/{calendar_class['id_calendar_class']}/attendance/open",
            headers=other_headers,
        )
    ).status_code == 403
    assert (
        await _list(client, other_headers, calendar_class["id_calendar_class"])
    ).status_code == 403


async def test_super_admin_manages_any_course(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    enrollment = await _enroll(client, admin, ANA_ID, sy)
    assert (
        await client.post(
            f"{URL}/{calendar_class['id_calendar_class']}/attendance/students/{enrollment['id_student_section_year']}",
            headers=admin,
        )
    ).status_code == 200


# ---------- check-in ----------
async def test_enrolled_student_checks_in(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    enrollment = await _enroll(client, admin, ANA_ID, sy)
    opened = await _open(client, admin, calendar_class["id_calendar_class"])

    r = await _checkin(
        client, await login(STUDENT), calendar_class["id_calendar_class"], opened["code"]
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id_student_section_year"] == enrollment["id_student_section_year"]
    assert body["id_section_year"] == sy
    assert body["method"] == "code"

    listed = (await _list(client, admin, calendar_class["id_calendar_class"])).json()
    assert listed["session"]["open"] is True
    assert len(listed["items"]) == 1
    assert listed["items"][0]["present"] is True
    assert listed["items"][0]["method"] == "code"

    history = (await client.get("/me/attendance", headers=await login(STUDENT))).json()
    assert len(history["items"]) == 1
    assert history["items"][0]["id_calendar_class"] == calendar_class["id_calendar_class"]
    assert history["items"][0]["section_name"] == "3K1"
    assert history["items"][0]["method"] == "code"


async def test_student_without_cursada_forbidden(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    opened = await _open(client, admin, calendar_class["id_calendar_class"])

    r = await _checkin(
        client, await login(LUIS), calendar_class["id_calendar_class"], opened["code"]
    )
    assert r.status_code == 403


async def test_professor_cannot_check_in(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    opened = await _open(client, admin, calendar_class["id_calendar_class"])
    mail = await make_professor("prof-checkin@frc.utn.edu.ar")
    await assign_professor(client, admin, mail, sy)

    r = await _checkin(
        client, await login(mail), calendar_class["id_calendar_class"], opened["code"]
    )
    assert r.status_code == 403


async def test_wrong_code_closed_and_expired(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    await _enroll(client, admin, ANA_ID, sy)
    opened = await _open(client, admin, calendar_class["id_calendar_class"])
    ana = await login(STUDENT)

    r = await _checkin(client, ana, calendar_class["id_calendar_class"], "000000")
    assert r.status_code == 422
    assert (
        await client.post(
            f"{URL}/{calendar_class['id_calendar_class']}/attendance/close",
            headers=admin,
        )
    ).status_code == 204
    r = await _checkin(client, ana, calendar_class["id_calendar_class"], opened["code"])
    assert r.status_code == 409

    # vencida: se adelanta el vencimiento en la base
    reopened = await _open(client, admin, calendar_class["id_calendar_class"])
    async with SessionLocal() as session:
        record = await session.get(
            AttendanceSession, reopened["id_attendance_session"]
        )
        record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        session.add(record)
        await session.commit()
    r = await _checkin(client, ana, calendar_class["id_calendar_class"], reopened["code"])
    assert r.status_code == 409


async def test_rotation_invalidates_previous_code(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    await _enroll(client, admin, ANA_ID, sy)
    first = await _open(client, admin, calendar_class["id_calendar_class"])
    second = await _open(client, admin, calendar_class["id_calendar_class"])
    assert first["code"] != second["code"]

    ana = await login(STUDENT)
    assert (
        await _checkin(client, ana, calendar_class["id_calendar_class"], first["code"])
    ).status_code == 422
    assert (
        await _checkin(client, ana, calendar_class["id_calendar_class"], second["code"])
    ).status_code == 200


async def test_check_in_is_idempotent(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    await _enroll(client, admin, ANA_ID, sy)
    opened = await _open(client, admin, calendar_class["id_calendar_class"])
    ana = await login(STUDENT)

    first = await _checkin(
        client, ana, calendar_class["id_calendar_class"], opened["code"]
    )
    second = await _checkin(
        client, ana, calendar_class["id_calendar_class"], opened["code"]
    )
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["id_attendance"] == second.json()["id_attendance"]
    history = (await client.get("/me/attendance", headers=ana)).json()
    assert len(history["items"]) == 1


async def test_code_from_other_class_does_not_work(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    class_a = await _class(client, admin, sy)
    class_b = await _class(client, admin, sy, date="2026-03-04")
    await _enroll(client, admin, ANA_ID, sy)
    opened_a = await _open(client, admin, class_a["id_calendar_class"])
    await _open(client, admin, class_b["id_calendar_class"])

    r = await _checkin(
        client, await login(STUDENT), class_b["id_calendar_class"], opened_a["code"]
    )
    assert r.status_code == 422


# ---------- manual ----------
async def test_manual_mark_and_unmark(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    enrollment = await _enroll(client, admin, ANA_ID, sy)
    url = (
        f"{URL}/{calendar_class['id_calendar_class']}/attendance/students/"
        f"{enrollment['id_student_section_year']}"
    )

    r = await client.post(url, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["method"] == "manual"
    assert (await client.post(url, headers=admin)).status_code == 200  # idempotente

    listed = (await _list(client, admin, calendar_class["id_calendar_class"])).json()
    assert listed["items"][0]["present"] is True
    assert listed["items"][0]["method"] == "manual"

    assert (await client.delete(url, headers=admin)).status_code == 204
    assert (await client.delete(url, headers=admin)).status_code == 404
    listed = (await _list(client, admin, calendar_class["id_calendar_class"])).json()
    assert listed["items"][0]["present"] is False
    assert listed["items"][0]["method"] is None


async def test_manual_foreign_enrollment_rejected(client, login):
    admin = await login(SUPER_ADMIN)
    sy_a = await _sy(client, admin, "3K1", 2026)
    sy_b = await _sy(client, admin, "3K2", 2026)
    calendar_class = await _class(client, admin, sy_a)
    enrollment_b = await _enroll(client, admin, ANA_ID, sy_b)

    r = await client.post(
        f"{URL}/{calendar_class['id_calendar_class']}/attendance/students/"
        f"{enrollment_b['id_student_section_year']}",
        headers=admin,
    )
    assert r.status_code == 422
    r = await client.post(
        f"{URL}/{calendar_class['id_calendar_class']}/attendance/students/999",
        headers=admin,
    )
    assert r.status_code == 404


async def test_list_includes_all_enrolled_in_order(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    ana = await _enroll(client, admin, ANA_ID, sy)
    await _enroll(client, admin, 2, sy)  # Luis
    opened = await _open(client, admin, calendar_class["id_calendar_class"])
    await _checkin(
        client, await login(STUDENT), calendar_class["id_calendar_class"], opened["code"]
    )

    listed = (await _list(client, admin, calendar_class["id_calendar_class"])).json()
    assert [item["last_name"] for item in listed["items"]] == ["Gómez", "Pérez"]
    by_enrollment = {
        item["id_student_section_year"]: item for item in listed["items"]
    }
    assert by_enrollment[ana["id_student_section_year"]]["present"] is True
    assert listed["items"][1]["present"] is False
    # el código no se expone
    assert set(listed["session"]) == {
        "id_attendance_session",
        "open",
        "opened_at",
        "expires_at",
        "closed_at",
    }


async def test_open_and_close_errors(client, login):
    admin = await login(SUPER_ADMIN)
    assert (
        await client.post(f"{URL}/999/attendance/open", headers=admin)
    ).status_code == 404
    assert (
        await client.post(f"{URL}/999/attendance/close", headers=admin)
    ).status_code == 404

    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    assert (
        await client.post(
            f"{URL}/{calendar_class['id_calendar_class']}/attendance/close",
            headers=admin,
        )
    ).status_code == 404


# ---------- historial y filtros ----------
async def test_my_attendance_filters_and_order(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    await _enroll(client, admin, ANA_ID, sy)
    march = await _class(client, admin, sy, date="2026-03-03")
    june = await _class(client, admin, sy, date="2026-06-02", start_time="19:00", end_time="21:00")
    ana = await login(STUDENT)
    for calendar_class in (march, june):
        opened = await _open(client, admin, calendar_class["id_calendar_class"])
        r = await _checkin(client, ana, calendar_class["id_calendar_class"], opened["code"])
        assert r.status_code == 200

    history = (await client.get("/me/attendance", headers=ana)).json()
    assert [item["date"] for item in history["items"]] == [
        "2026-06-02",
        "2026-03-03",
    ]

    filtered = (
        await client.get(
            "/me/attendance",
            params={"from": "2026-03-01", "to": "2026-03-31"},
            headers=ana,
        )
    ).json()
    assert [item["date"] for item in filtered["items"]] == ["2026-03-03"]

    assert (
        await client.get("/me/attendance", params={"from": "2026-03-01"}, headers=ana)
    ).status_code == 422
    assert (
        await client.get(
            "/me/attendance",
            params={"from": "2026-06-01", "to": "2026-03-01"},
            headers=ana,
        )
    ).status_code == 422
    assert (
        await client.get(
            "/me/attendance",
            params={"from": "2025-01-01", "to": "2026-01-03"},
            headers=ana,
        )
    ).status_code == 422


async def test_my_attendance_is_student_only(client, login):
    assert (
        await client.get("/me/attendance", headers=await login(SUPER_ADMIN))
    ).status_code == 403


# ---------- cascadas ----------
async def test_delete_class_removes_session_and_attendance(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    await _enroll(client, admin, ANA_ID, sy)
    opened = await _open(client, admin, calendar_class["id_calendar_class"])
    await _checkin(
        client, await login(STUDENT), calendar_class["id_calendar_class"], opened["code"]
    )

    assert (
        await client.delete(
            f"/calendar-classes/{calendar_class['id_calendar_class']}", headers=admin
        )
    ).status_code == 204
    assert (
        await client.get(
            f"{URL}/{calendar_class['id_calendar_class']}/attendance", headers=admin
        )
    ).status_code == 404
    async with SessionLocal() as session:
        rows = (
            await session.exec(select(AttendanceSession))
        ).all()
        assert rows == []
    history = (await client.get("/me/attendance", headers=await login(STUDENT))).json()
    assert history["items"] == []


async def test_delete_enrollment_removes_attendance(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    enrollment = await _enroll(client, admin, ANA_ID, sy)
    opened = await _open(client, admin, calendar_class["id_calendar_class"])
    await _checkin(
        client, await login(STUDENT), calendar_class["id_calendar_class"], opened["code"]
    )

    assert (
        await client.delete(
            f"/student-section-years/{enrollment['id_student_section_year']}",
            headers=admin,
        )
    ).status_code == 204
    history = (await client.get("/me/attendance", headers=await login(STUDENT))).json()
    assert history["items"] == []
