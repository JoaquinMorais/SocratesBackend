from tests.helpers import (
    STUDENT,
    SUPER_ADMIN,
    assign_professor,
    create_cursada,
    section_year,
)

URL = "/me/calendar"
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


def _activity_body(**overrides) -> dict:
    return {
        "title": "Entrega",
        "due_date": "2026-05-15",
        "due_time": "23:59",
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


async def _activity(client, headers, id_section_year: int, **overrides) -> dict:
    r = await client.post(
        f"/section-years/{id_section_year}/activities",
        json=_activity_body(**overrides),
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _enroll(client, headers, id_student: int, id_section_year: int) -> None:
    r = await client.post(
        "/student-section-years",
        json={"id_student": id_student, "id_section_year": id_section_year},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    await create_cursada(id_student, id_section_year)


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


async def _calendar(client, headers, **params):
    return await client.get(URL, params=params, headers=headers)


async def test_requires_authentication(client):
    assert (await client.get(URL)).status_code == 401


async def test_professor_gets_current_year_across_commissions(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    mail = await make_professor("prof-calendario@frc.utn.edu.ar")
    sy_a = await _sy(client, admin, "3K1", 2026)
    sy_b = await _sy(client, admin, "3K2", 2026)
    sy_old = await _sy(client, admin, "3K3", 2025)
    for sy in (sy_a, sy_b, sy_old):
        await assign_professor(client, admin, mail, sy)
    class_a = await _class(client, admin, sy_a)
    class_b = await _class(client, admin, sy_b)
    class_old = await _class(client, admin, sy_old, date="2025-03-04")
    await _activity(client, admin, sy_a)
    await _activity(client, admin, sy_b)
    await _activity(client, admin, sy_old, due_date="2025-05-15")

    body = (await _calendar(client, await login(mail))).json()
    assert [sy["id_section_year"] for sy in body["section_years"]] == [sy_a, sy_b]
    assert {c["id_calendar_class"] for c in body["classes"]} == {
        class_a["id_calendar_class"],
        class_b["id_calendar_class"],
    }
    assert class_old["id_calendar_class"] not in {
        c["id_calendar_class"] for c in body["classes"]
    }
    assert len(body["activities"]) == 2
    assert {a["id_section_year"] for a in body["activities"]} == {sy_a, sy_b}


async def test_student_gets_current_cursada_year(client, login):
    admin = await login(SUPER_ADMIN)
    sy_old = await _sy(client, admin, "3K1", 2025)
    sy_now = await _sy(client, admin, "3K2", 2026)
    await _enroll(client, admin, ANA_ID, sy_old)
    await create_cursada(ANA_ID, sy_old, state="finished_approved")
    await _enroll(client, admin, ANA_ID, sy_now)
    class_old = await _class(client, admin, sy_old, date="2025-03-04")
    class_now = await _class(client, admin, sy_now)
    await _activity(client, admin, sy_old, due_date="2025-05-15")
    activity_now = await _activity(client, admin, sy_now)

    body = (await _calendar(client, await login(STUDENT))).json()
    assert [sy["id_section_year"] for sy in body["section_years"]] == [sy_now]
    assert [c["id_calendar_class"] for c in body["classes"]] == [
        class_now["id_calendar_class"]
    ]
    assert class_old["id_calendar_class"] not in {
        c["id_calendar_class"] for c in body["classes"]
    }
    assert [a["id_activity"] for a in body["activities"]] == [activity_now["id_activity"]]


async def test_student_falls_back_to_current_group(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    class_ = await _class(client, admin, sy)
    activity = await _activity(client, admin, sy)
    lu = await login(LUIS)
    await _join_project(client, admin, lu, sy)

    body = (await _calendar(client, lu)).json()
    assert [s["id_section_year"] for s in body["section_years"]] == [sy]
    assert [c["id_calendar_class"] for c in body["classes"]] == [
        class_["id_calendar_class"]
    ]
    assert [a["id_activity"] for a in body["activities"]] == [activity["id_activity"]]


async def test_registered_student_sees_inscribed_calendar(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin, "3K1", 2026)
    class_ = await _class(client, admin, sy)
    activity = await _activity(client, admin, sy)
    r = await client.post(
        "/student-section-years",
        json={"id_student": ANA_ID, "id_section_year": sy},
        headers=admin,
    )
    assert r.status_code == 201, r.text

    body = (await _calendar(client, await login(STUDENT))).json()
    assert [section["id_section_year"] for section in body["section_years"]] == [sy]
    assert [item["id_calendar_class"] for item in body["classes"]] == [
        class_["id_calendar_class"]
    ]
    assert [item["id_activity"] for item in body["activities"]] == [
        activity["id_activity"]
    ]


async def test_no_current_section_year(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sin_asignaciones = await make_professor("prof-sin-cal@frc.utn.edu.ar")
    for headers in (
        await login(sin_asignaciones),
        await login(STUDENT),
        admin,
    ):
        body = (await _calendar(client, headers)).json()
        assert body == {"section_years": [], "classes": [], "activities": []}


async def test_range_validation_and_filtering(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    await _enroll(client, admin, ANA_ID, sy)
    await _class(client, admin, sy, date="2026-03-03")
    june_class = await _class(client, admin, sy, date="2026-06-02")
    await _activity(client, admin, sy, due_date="2026-03-20")
    june_activity = await _activity(client, admin, sy, due_date="2026-06-20")
    headers = await login(STUDENT)

    body = (
        await _calendar(
            client, headers, **{"from": "2026-03-01", "to": "2026-03-31"}
        )
    ).json()
    assert [c["date"] for c in body["classes"]] == ["2026-03-03"]
    assert [a["due_date"] for a in body["activities"]] == ["2026-03-20"]

    assert (await _calendar(client, headers, **{"from": "2026-03-01"})).status_code == 422
    assert (
        await _calendar(client, headers, **{"from": "2026-06-01", "to": "2026-03-01"})
    ).status_code == 422
    assert (
        await _calendar(client, headers, **{"from": "2025-01-01", "to": "2026-01-03"})
    ).status_code == 422

    all_body = (await _calendar(client, headers)).json()
    assert june_class["id_calendar_class"] in {
        c["id_calendar_class"] for c in all_body["classes"]
    }
    assert june_activity["id_activity"] in {
        a["id_activity"] for a in all_body["activities"]
    }


async def test_ordering(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    await _enroll(client, admin, ANA_ID, sy)
    await _class(client, admin, sy, date="2026-06-02", start_time="19:00", end_time="21:00")
    await _class(client, admin, sy, date="2026-03-03", start_time="18:30", end_time="22:00")
    await _activity(client, admin, sy, title="B", due_date="2026-06-10")
    await _activity(client, admin, sy, title="A", due_date="2026-05-15")

    body = (await _calendar(client, await login(STUDENT))).json()
    assert [c["date"] for c in body["classes"]] == ["2026-03-03", "2026-06-02"]
    assert [a["title"] for a in body["activities"]] == ["A", "B"]


async def test_super_admin_with_assignments_gets_calendar(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    mail = await make_professor("super-calendario@frc.utn.edu.ar", is_super_admin=True)
    sy = await _sy(client, admin)
    await assign_professor(client, admin, mail, sy)
    class_ = await _class(client, admin, sy)
    activity = await _activity(client, admin, sy)

    body = (await _calendar(client, await login(mail))).json()
    assert [section["id_section_year"] for section in body["section_years"]] == [sy]
    assert [item["id_calendar_class"] for item in body["classes"]] == [
        class_["id_calendar_class"]
    ]
    assert [item["id_activity"] for item in body["activities"]] == [
        activity["id_activity"]
    ]


async def test_student_prefers_attending_over_registered_for_calendar(client, login):
    admin = await login(SUPER_ADMIN)
    sy_a = await _sy(client, admin, "3K1", 2026)
    sy_b = await _sy(client, admin, "3K2", 2026)
    r = await client.post(
        "/student-section-years",
        json={"id_student": ANA_ID, "id_section_year": sy_a},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    await create_cursada(ANA_ID, sy_b)

    class_a = await _class(client, admin, sy_a)
    activity_a = await _activity(client, admin, sy_a)
    class_b = await _class(client, admin, sy_b, date="2026-04-07")
    activity_b = await _activity(
        client, admin, sy_b, due_date="2026-06-10"
    )

    body = (await _calendar(client, await login(STUDENT))).json()
    assert [section["id_section_year"] for section in body["section_years"]] == [sy_b]
    assert [item["id_calendar_class"] for item in body["classes"]] == [
        class_b["id_calendar_class"]
    ]
    assert [item["id_activity"] for item in body["activities"]] == [
        activity_b["id_activity"]
    ]
    assert class_a["id_calendar_class"] not in {
        item["id_calendar_class"] for item in body["classes"]
    }
    assert activity_a["id_activity"] not in {
        item["id_activity"] for item in body["activities"]
    }
