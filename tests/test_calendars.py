from datetime import date

from sqlmodel import delete as sql_delete

from config.database import SessionLocal
from models import Calendar
from tests.helpers import STUDENT, SUPER_ADMIN, assign_professor, section_year

URL = "/section-years"
ITEM = "/calendar-classes"
ANA_ID = 1
LUIS = "100002@sistemas.frc.utn.edu.ar"


def _body(**overrides) -> dict:
    return {
        "date": "2026-03-03",  # martes
        "start_time": "18:30",
        "end_time": "22:00",
        "modality": "in_person",
        **overrides,
    }


def _bulk(**overrides) -> dict:
    return {
        "weekdays": [2],
        "from_date": "2026-03-01",
        "to_date": "2026-03-31",
        "start_time": "18:30",
        "end_time": "22:00",
        "modality": "in_person",
        **overrides,
    }


async def _sy(client, headers, name: str = "3K1", year: int = 2026) -> int:
    return await section_year(client, headers, name, year)


async def _create(client, headers, id_section_year: int, **overrides) -> dict:
    r = await client.post(
        f"{URL}/{id_section_year}/calendar-classes",
        json=_body(**overrides),
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _bulk_create(client, headers, id_section_year: int, **overrides):
    return await client.post(
        f"{URL}/{id_section_year}/calendar-classes/bulk",
        json=_bulk(**overrides),
        headers=headers,
    )


async def _calendar(client, headers, id_section_year: int, **params):
    return await client.get(f"{URL}/{id_section_year}/calendar", params=params, headers=headers)


async def _enroll(client, headers, id_student: int, id_section_year: int) -> None:
    r = await client.post(
        "/student-section-years",
        json={"id_student": id_student, "id_section_year": id_section_year},
        headers=headers,
    )
    assert r.status_code == 201, r.text


async def _join_project(client, admin, student_headers, id_section_year: int) -> dict:
    r = await client.post(
        "/projects", json={"id_section_year": id_section_year}, headers=admin
    )
    assert r.status_code == 201, r.text
    project = r.json()
    r = await client.post(
        f"/projects/{project['id_project']}/members", headers=student_headers
    )
    assert r.status_code == 201, r.text
    return project


# ---------- permisos ----------
async def test_requires_authentication(client):
    assert (await client.get(f"{URL}/1/calendar")).status_code == 401
    assert (
        await client.post(f"{URL}/1/calendar-classes", json=_body())
    ).status_code == 401
    assert (
        await client.post(f"{URL}/1/calendar-classes/bulk", json=_bulk())
    ).status_code == 401
    assert (
        await client.patch(f"{URL}/1/calendar-classes/bulk", json={"ids": [1], "changes": {"modality": "virtual"}})
    ).status_code == 401
    assert (
        await client.request(
            "DELETE", f"{URL}/1/calendar-classes/bulk", json={"ids": [1]}
        )
    ).status_code == 401
    assert (await client.get(f"{ITEM}/1")).status_code == 401
    assert (await client.patch(f"{ITEM}/1", json={"modality": "virtual"})).status_code == 401
    assert (await client.delete(f"{ITEM}/1")).status_code == 401


async def test_student_of_other_course_forbidden(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _create(client, admin, sy)
    headers = await login(STUDENT)  # Ana no cursa ese curso

    assert (await _calendar(client, headers, sy)).status_code == 403
    assert (await client.get(f"{ITEM}/{calendar_class['id_calendar_class']}", headers=headers)).status_code == 403
    assert (
        await client.post(f"{URL}/{sy}/calendar-classes", json=_body(date="2026-03-10"), headers=headers)
    ).status_code == 403
    assert (
        await client.post(f"{URL}/{sy}/calendar-classes/bulk", json=_bulk(), headers=headers)
    ).status_code == 403


async def test_enrolled_student_can_read_but_not_write(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _create(client, admin, sy)
    await _enroll(client, admin, ANA_ID, sy)
    headers = await login(STUDENT)

    assert (await _calendar(client, headers, sy)).status_code == 200
    assert (
        await client.get(f"{ITEM}/{calendar_class['id_calendar_class']}", headers=headers)
    ).status_code == 200
    assert (
        await client.post(f"{URL}/{sy}/calendar-classes", json=_body(date="2026-03-10"), headers=headers)
    ).status_code == 403


async def test_member_of_project_can_read(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    await _create(client, admin, sy)
    lu = await login(LUIS)
    await _join_project(client, admin, lu, sy)

    assert (await _calendar(client, lu, sy)).status_code == 200


async def test_assigned_professor_manages_and_other_cannot(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    assigned = await make_professor("prof-cal@frc.utn.edu.ar")
    other = await make_professor("prof-cal-otro@frc.utn.edu.ar", legajo=300001)
    await assign_professor(client, admin, assigned, sy)

    assigned_headers = await login(assigned)
    calendar_class = await _create(client, assigned_headers, sy)
    assert (await _calendar(client, assigned_headers, sy)).status_code == 200
    assert (
        await client.patch(
            f"{ITEM}/{calendar_class['id_calendar_class']}",
            json={"modality": "virtual"},
            headers=assigned_headers,
        )
    ).status_code == 200
    assert (
        await client.delete(
            f"{ITEM}/{calendar_class['id_calendar_class']}", headers=assigned_headers
        )
    ).status_code == 204

    other_headers = await login(other)
    assert (await _calendar(client, other_headers, sy)).status_code == 403
    created = await _create(client, admin, sy)
    assert (
        await client.get(f"{ITEM}/{created['id_calendar_class']}", headers=other_headers)
    ).status_code == 403
    assert (
        await client.post(
            f"{URL}/{sy}/calendar-classes", json=_body(date="2026-03-10"), headers=other_headers
        )
    ).status_code == 403


async def test_super_admin_manages_any_course(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _create(client, admin, sy)
    assert (
        await client.delete(f"{ITEM}/{calendar_class['id_calendar_class']}", headers=admin)
    ).status_code == 204


# ---------- calendario ----------
async def test_calendar_is_one_per_section_year(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    first = (await _calendar(client, admin, sy)).json()
    second = (await _calendar(client, admin, sy)).json()
    assert first["id_calendar"] == second["id_calendar"]
    assert first["id_section_year"] == sy
    assert first["classes"] == []
    assert set(first) == {
        "id_calendar",
        "id_section_year",
        "timezone",
        "classes",
        "activities",
    }


async def test_calendar_created_if_missing(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    async with SessionLocal() as session:
        await session.exec(sql_delete(Calendar).where(Calendar.id_section_year == sy))
        await session.commit()
    body = (await _calendar(client, admin, sy)).json()
    assert body["id_section_year"] == sy
    assert body["classes"] == []


async def test_calendar_range_validation(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    assert (await _calendar(client, admin, sy, **{"from": "2026-03-01"})).status_code == 422
    assert (
        await _calendar(client, admin, sy, **{"from": "2026-03-31", "to": "2026-03-01"})
    ).status_code == 422
    assert (
        await _calendar(client, admin, sy, **{"from": "2025-01-01", "to": "2026-01-03"})
    ).status_code == 422
    assert (await _calendar(client, admin, sy, **{"from": "2026-03-01", "to": "2026-03-31"})).status_code == 200


async def test_calendar_filters_by_range(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    await _create(client, admin, sy, date="2026-03-03")
    await _create(client, admin, sy, date="2026-05-05")
    body = (await _calendar(client, admin, sy, **{"from": "2026-03-01", "to": "2026-03-31"})).json()
    assert [c["date"] for c in body["classes"]] == ["2026-03-03"]


async def test_calendar_includes_activities(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    await _create(client, admin, sy, date="2026-03-03")
    march = (
        await client.post(
            f"{URL}/{sy}/activities",
            json={"title": "Marzo", "due_date": "2026-03-20"},
            headers=admin,
        )
    ).json()
    june = (
        await client.post(
            f"{URL}/{sy}/activities",
            json={"title": "Junio", "due_date": "2026-06-20"},
            headers=admin,
        )
    ).json()
    body = (await _calendar(client, admin, sy, **{"from": "2026-03-01", "to": "2026-03-31"})).json()
    assert [a["id_activity"] for a in body["activities"]] == [march["id_activity"]]
    assert june["id_activity"] not in {a["id_activity"] for a in body["activities"]}

    complete = (await _calendar(client, admin, sy)).json()
    assert {a["id_activity"] for a in complete["activities"]} == {
        march["id_activity"],
        june["id_activity"],
    }


# ---------- clase puntual ----------
async def test_create_calendar_class(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    created = await _create(client, admin, sy, title="Teórica", location="Aula 12")
    assert created["date"] == "2026-03-03"
    assert created["weekday"] == 2  # martes
    assert created["start_time"] == "18:30:00"
    assert created["end_time"] == "22:00:00"
    assert created["modality"] == "in_person"
    assert created["title"] == "Teórica" and created["location"] == "Aula 12"
    assert set(created) == {
        "id_calendar_class",
        "id_calendar",
        "date",
        "weekday",
        "start_time",
        "end_time",
        "modality",
        "title",
        "location",
        "meeting_url",
    }


async def test_create_validation(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    invalid = [
        _body(end_time="18:30"),
        _body(end_time="17:00"),
        _body(meeting_url="no-es-url"),
        _body(otro=1),
        _body(date="2027-03-03"),  # fuera del año del curso
        {"date": "2026-03-03", "start_time": "18:30"},  # falta end_time
    ]
    for body in invalid:
        r = await client.post(f"{URL}/{sy}/calendar-classes", json=body, headers=admin)
        assert r.status_code == 422, body
    assert (
        await client.post(f"{URL}/999/calendar-classes", json=_body(), headers=admin)
    ).status_code == 404


async def test_duplicate_and_overlap(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    await _create(client, admin, sy)
    assert (
        await client.post(f"{URL}/{sy}/calendar-classes", json=_body(), headers=admin)
    ).status_code == 409
    assert (
        await client.post(
            f"{URL}/{sy}/calendar-classes",
            json=_body(start_time="21:00", end_time="23:00"),
            headers=admin,
        )
    ).status_code == 409
    # contiguo y otro día son válidos
    assert (
        await client.post(
            f"{URL}/{sy}/calendar-classes",
            json=_body(start_time="22:00", end_time="23:00"),
            headers=admin,
        )
    ).status_code == 201
    assert (
        await client.post(f"{URL}/{sy}/calendar-classes", json=_body(date="2026-03-04"), headers=admin)
    ).status_code == 201


async def test_get_not_found(client, login):
    assert (await client.get(f"{ITEM}/999", headers=await login(SUPER_ADMIN))).status_code == 404


async def test_patch_calendar_class(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    created = await _create(client, admin, sy, title="Teórica", location="Aula 1")
    url = f"{ITEM}/{created['id_calendar_class']}"

    r = await client.patch(
        url,
        json={
            "date": "2026-03-05",
            "start_time": "19:00",
            "end_time": "21:00",
            "modality": "virtual",
            "meeting_url": "https://meet.example.com/clase",
        },
        headers=admin,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["date"] == "2026-03-05" and body["weekday"] == 4
    assert body["start_time"] == "19:00:00" and body["end_time"] == "21:00:00"
    assert body["modality"] == "virtual"
    assert body["meeting_url"] == "https://meet.example.com/clase"

    r = await client.patch(url, json={"title": None, "location": None}, headers=admin)
    assert r.status_code == 200 and r.json()["title"] is None and r.json()["location"] is None

    assert (await client.patch(url, json={}, headers=admin)).status_code == 422
    assert (await client.patch(url, json={"otro": 1}, headers=admin)).status_code == 422
    assert (await client.patch(url, json={"date": "2027-03-05"}, headers=admin)).status_code == 422
    assert (await client.patch(f"{ITEM}/999", json={"modality": "virtual"}, headers=admin)).status_code == 404


async def test_patch_overlap_rejected(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    await _create(client, admin, sy)  # 18:30-22:00
    second = await _create(client, admin, sy, date="2026-03-04")
    r = await client.patch(
        f"{ITEM}/{second['id_calendar_class']}",
        json={"date": "2026-03-03", "start_time": "19:00", "end_time": "20:00"},
        headers=admin,
    )
    assert r.status_code == 409


async def test_delete_and_cascade(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    created = await _create(client, admin, sy)
    assert (await client.delete(f"{ITEM}/{created['id_calendar_class']}", headers=admin)).status_code == 204
    assert (await client.get(f"{ITEM}/{created['id_calendar_class']}", headers=admin)).status_code == 404
    assert (await client.delete(f"{ITEM}/{created['id_calendar_class']}", headers=admin)).status_code == 404

    other_sy = await _sy(client, admin, "3K2", 2026)
    other = await _create(client, admin, other_sy)
    assert (await client.delete(f"{URL}/{other_sy}", headers=admin)).status_code == 204
    assert (await client.get(f"{ITEM}/{other['id_calendar_class']}", headers=admin)).status_code == 404


# ---------- creación en lote ----------
async def test_bulk_create(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    r = await _bulk_create(client, admin, sy, weekdays=[2, 3])
    assert r.status_code == 201, r.text
    items = r.json()
    assert len(items) == 9  # 5 martes + 4 miércoles de marzo de 2026
    assert [item["date"] for item in items] == [
        "2026-03-03",
        "2026-03-04",
        "2026-03-10",
        "2026-03-11",
        "2026-03-17",
        "2026-03-18",
        "2026-03-24",
        "2026-03-25",
        "2026-03-31",
    ]
    assert {item["weekday"] for item in items} == {2, 3}
    assert all(item["start_time"] == "18:30:00" for item in items)


async def test_bulk_conflict_is_all_or_nothing(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    await _create(client, admin, sy, date="2026-03-10")  # ya hay clase ese martes
    r = await _bulk_create(client, admin, sy, weekdays=[2])
    assert r.status_code == 409
    assert [conflict["date"] for conflict in r.json()["detail"]] == ["2026-03-10"]
    # no se creó ninguna otra
    body = (await _calendar(client, admin, sy)).json()
    assert [c["date"] for c in body["classes"]] == ["2026-03-10"]


async def test_bulk_validation(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    assert (await _bulk_create(client, admin, sy, weekdays=[0])).status_code == 422
    assert (await _bulk_create(client, admin, sy, weekdays=[8])).status_code == 422
    assert (
        await _bulk_create(client, admin, sy, **{"from_date": "2026-03-31", "to_date": "2026-03-01"})
    ).status_code == 422
    assert (
        await _bulk_create(client, admin, sy, **{"from_date": "2025-03-01", "to_date": "2025-11-30"})
    ).status_code == 422  # fuera del año del curso
    # ningún martes en un rango de un solo lunes
    assert (
        await _bulk_create(client, admin, sy, weekdays=[2], **{"from_date": "2026-03-02", "to_date": "2026-03-02"})
    ).status_code == 422
    # días repetidos se deduplican
    r = await _bulk_create(client, admin, sy, weekdays=[2, 2], **{"from_date": "2026-03-03", "to_date": "2026-03-03"})
    assert r.status_code == 201 and len(r.json()) == 1


# ---------- modificación en lote ----------
async def test_bulk_update_by_ids(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    first = await _create(client, admin, sy)
    second = await _create(client, admin, sy, date="2026-03-04")
    r = await client.patch(
        f"{URL}/{sy}/calendar-classes/bulk",
        json={
            "ids": [first["id_calendar_class"], second["id_calendar_class"]],
            "changes": {"modality": "virtual", "start_time": "19:00", "end_time": "21:00"},
        },
        headers=admin,
    )
    assert r.status_code == 200, r.text
    assert all(item["modality"] == "virtual" for item in r.json())
    assert all(item["start_time"] == "19:00:00" for item in r.json())


async def test_bulk_update_by_filter(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    await _create(client, admin, sy)  # martes
    await _create(client, admin, sy, date="2026-03-04")  # miércoles
    r = await client.patch(
        f"{URL}/{sy}/calendar-classes/bulk",
        json={
            "filter": {"weekdays": [2], "from_date": "2026-03-01", "to_date": "2026-03-31"},
            "changes": {"title": "Solo martes"},
        },
        headers=admin,
    )
    assert r.status_code == 200
    assert [item["title"] for item in r.json()] == ["Solo martes"]
    body = (await _calendar(client, admin, sy)).json()
    assert {c["date"]: c["title"] for c in body["classes"]} == {
        "2026-03-03": "Solo martes",
        "2026-03-04": None,
    }


async def test_bulk_update_overlap_is_rejected(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    early = await _create(client, admin, sy, start_time="10:00", end_time="12:00")
    await _create(client, admin, sy, start_time="14:00", end_time="16:00")
    r = await client.patch(
        f"{URL}/{sy}/calendar-classes/bulk",
        json={"ids": [early["id_calendar_class"]], "changes": {"start_time": "15:00", "end_time": "17:00"}},
        headers=admin,
    )
    assert r.status_code == 409
    body = (await _calendar(client, admin, sy)).json()
    assert body["classes"][0]["start_time"] == "10:00:00"  # no cambió


async def test_bulk_update_validation(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    created = await _create(client, admin, sy)
    url = f"{URL}/{sy}/calendar-classes/bulk"
    assert (
        await client.patch(
            url,
            json={
                "ids": [created["id_calendar_class"]],
                "filter": {"weekdays": [2]},
                "changes": {"modality": "virtual"},
            },
            headers=admin,
        )
    ).status_code == 422
    assert (await client.patch(url, json={"changes": {"modality": "virtual"}}, headers=admin)).status_code == 422
    assert (await client.patch(url, json={"ids": [created["id_calendar_class"]], "changes": {}}, headers=admin)).status_code == 422
    assert (
        await client.patch(
            url,
            json={"ids": [created["id_calendar_class"]], "changes": {"date": "2026-03-04"}},
            headers=admin,
        )
    ).status_code == 422
    assert (
        await client.patch(
            url,
            json={"filter": {"from_date": "2026-04-01", "to_date": "2026-04-30"}, "changes": {"modality": "virtual"}},
            headers=admin,
        )
    ).status_code == 422  # ninguna coincide


# ---------- borrado en lote (feriado) ----------
async def test_bulk_delete_by_filter(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    await _create(client, admin, sy, date="2026-04-01")
    await _create(client, admin, sy, date="2026-04-02")
    r = await client.request(
        "DELETE",
        f"{URL}/{sy}/calendar-classes/bulk",
        json={"filter": {"from_date": "2026-04-02", "to_date": "2026-04-02"}},
        headers=admin,
    )
    assert r.status_code == 204, r.text
    body = (await _calendar(client, admin, sy)).json()
    assert [c["date"] for c in body["classes"]] == ["2026-04-01"]


async def test_bulk_delete_by_ids(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    first = await _create(client, admin, sy)
    await _create(client, admin, sy, date="2026-03-04")
    r = await client.request(
        "DELETE",
        f"{URL}/{sy}/calendar-classes/bulk",
        json={"ids": [first["id_calendar_class"]]},
        headers=admin,
    )
    assert r.status_code == 204
    body = (await _calendar(client, admin, sy)).json()
    assert [c["date"] for c in body["classes"]] == ["2026-03-04"]


async def test_bulk_delete_validation(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    created = await _create(client, admin, sy)
    url = f"{URL}/{sy}/calendar-classes/bulk"
    assert (await client.request("DELETE", url, json={}, headers=admin)).status_code == 422
    assert (
        await client.request(
            "DELETE",
            url,
            json={"ids": [created["id_calendar_class"]], "filter": {"weekdays": [2]}},
            headers=admin,
        )
    ).status_code == 422
    assert (
        await client.request(
            "DELETE",
            url,
            json={"filter": {"from_date": "2026-04-01", "to_date": "2026-04-30"}},
            headers=admin,
        )
    ).status_code == 422
