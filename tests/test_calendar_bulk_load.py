from tests.helpers import STUDENT, SUPER_ADMIN, assign_professor, section_year

URL = "/section-years"
ANA_ID = 1


def _class(**overrides) -> dict:
    return {
        "date": "2026-03-03",
        "start_time": "18:30",
        "end_time": "22:00",
        "modality": "in_person",
        **overrides,
    }


def _activity(**overrides) -> dict:
    return {
        "title": "Entrega del informe",
        "description": "Avance del proyecto",
        "due_date": "2026-05-15",
        "due_time": "23:59",
        **overrides,
    }


async def _sy(client, headers, name: str = "3K1", year: int = 2026) -> int:
    return await section_year(client, headers, name, year)


async def _bulk(
    client,
    headers,
    id_section_year: int,
    *,
    classes=None,
    activities=None,
    dry_run=None,
):
    body: dict = {}
    if classes is not None:
        body["classes"] = classes
    if activities is not None:
        body["activities"] = activities
    params = {} if dry_run is None else {"dry_run": dry_run}
    return await client.post(
        f"{URL}/{id_section_year}/calendar/bulk",
        json=body,
        params=params,
        headers=headers,
    )


async def _calendar(client, headers, id_section_year: int) -> dict:
    r = await client.get(f"{URL}/{id_section_year}/calendar", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- permisos ----------
async def test_requires_authentication(client):
    assert (
        await client.post(f"{URL}/1/calendar/bulk", json={"classes": [_class()]})
    ).status_code == 401


async def test_permissions(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    assigned = await make_professor("prof-bulk-cal@frc.utn.edu.ar")
    other = await make_professor("prof-bulk-cal-otro@frc.utn.edu.ar", legajo=300001)
    await assign_professor(client, admin, assigned, sy)

    assert (
        await _bulk(client, await login(STUDENT), sy, classes=[_class()])
    ).status_code == 403
    assert (
        await _bulk(client, await login(other), sy, classes=[_class()])
    ).status_code == 403

    r = await _bulk(client, await login(assigned), sy, classes=[_class()])
    assert r.status_code == 201, r.text

    r = await _bulk(
        client, admin, sy, classes=[_class(date="2026-03-04")]
    )
    assert r.status_code == 201, r.text

    assert (
        await _bulk(client, admin, 999, classes=[_class()])
    ).status_code == 404


# ---------- carga feliz ----------
async def test_load_classes_and_activities(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)

    r = await _bulk(
        client,
        admin,
        sy,
        classes=[
            _class(date="2026-03-03"),
            _class(date="2026-03-04", start_time="09:00", end_time="12:00"),
        ],
        activities=[_activity()],
    )
    assert r.status_code == 201, r.text
    assert r.json() == {
        "dry_run": False,
        "classes_created": 2,
        "activities_created": 1,
    }

    calendar = await _calendar(client, admin, sy)
    assert len(calendar["classes"]) == 2
    assert len(calendar["activities"]) == 1
    assert calendar["activities"][0]["title"] == "Entrega del informe"


async def test_classes_only_and_activities_only(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)

    r = await _bulk(client, admin, sy, classes=[_class()])
    assert r.status_code == 201
    assert r.json()["classes_created"] == 1
    assert r.json()["activities_created"] == 0

    r = await _bulk(client, admin, sy, activities=[_activity()])
    assert r.status_code == 201
    assert r.json()["classes_created"] == 0
    assert r.json()["activities_created"] == 1

    assert (await _bulk(client, admin, sy)).status_code == 422


async def test_dry_run_does_not_write(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)

    r = await _bulk(
        client,
        admin,
        sy,
        classes=[_class()],
        activities=[_activity()],
        dry_run="true",
    )
    assert r.status_code == 200, r.text
    assert r.json() == {
        "dry_run": True,
        "classes_created": 1,
        "activities_created": 1,
    }
    calendar = await _calendar(client, admin, sy)
    assert calendar["classes"] == [] and calendar["activities"] == []

    r = await _bulk(
        client, admin, sy, classes=[_class()], activities=[_activity()]
    )
    assert r.status_code == 201
    calendar = await _calendar(client, admin, sy)
    assert len(calendar["classes"]) == 1 and len(calendar["activities"]) == 1


# ---------- validaciones ----------
async def test_dates_and_invalid_data(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)

    r = await _bulk(client, admin, sy, classes=[_class(date="2027-03-03")])
    assert r.status_code == 422
    assert r.json()["detail"][0]["kind"] == "class"
    assert r.json()["detail"][0]["row"] == 1

    r = await _bulk(client, admin, sy, activities=[_activity(due_date="2027-05-15")])
    assert r.status_code == 422
    assert r.json()["detail"][0]["kind"] == "activity"

    assert (
        await _bulk(client, admin, sy, classes=[_class(end_time="18:30")])
    ).status_code == 422
    assert (
        await _bulk(client, admin, sy, classes=[_class(meeting_url="no-es-url")])
    ).status_code == 422
    assert (
        await _bulk(client, admin, sy, classes=[_class(otro=1)])
    ).status_code == 422
    assert (
        await _bulk(client, admin, sy, activities=[_activity(title="  ")])
    ).status_code == 422


async def test_limits(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    too_many_classes = [_class() for _ in range(1001)]
    assert (await _bulk(client, admin, sy, classes=too_many_classes)).status_code == 422
    too_many_activities = [_activity() for _ in range(201)]
    assert (
        await _bulk(client, admin, sy, activities=too_many_activities)
    ).status_code == 422


async def test_overlaps_within_payload(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)

    r = await _bulk(
        client,
        admin,
        sy,
        classes=[
            _class(),
            _class(start_time="21:00", end_time="23:00"),
        ],
    )
    assert r.status_code == 422
    assert r.json()["detail"] == [
        {
            "kind": "class",
            "row": 2,
            "detail": "Overlaps another class on 2026-03-03",
        }
    ]
    calendar = await _calendar(client, admin, sy)
    assert calendar["classes"] == []

    # duplicado exacto
    r = await _bulk(client, admin, sy, classes=[_class(), _class()])
    assert r.status_code == 422


async def test_touching_and_same_day_different_times_allowed(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    r = await _bulk(
        client,
        admin,
        sy,
        classes=[
            _class(start_time="10:00", end_time="12:00"),
            _class(start_time="12:00", end_time="14:00"),
            _class(start_time="16:00", end_time="18:00"),
        ],
    )
    assert r.status_code == 201, r.text
    assert r.json()["classes_created"] == 3


async def test_all_or_nothing_with_invalid_row(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    r = await _bulk(
        client,
        admin,
        sy,
        classes=[_class(), _class(date="2027-01-01")],
        activities=[_activity()],
    )
    assert r.status_code == 422
    calendar = await _calendar(client, admin, sy)
    assert calendar["classes"] == [] and calendar["activities"] == []


async def test_conflict_with_existing_is_all_or_nothing(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    r = await client.post(
        f"{URL}/{sy}/calendar-classes", json=_class(), headers=admin
    )
    assert r.status_code == 201, r.text

    r = await _bulk(
        client,
        admin,
        sy,
        classes=[_class(start_time="19:00", end_time="20:00")],
        activities=[_activity()],
    )
    assert r.status_code == 409
    assert r.json()["detail"][0]["kind"] == "class"
    assert r.json()["detail"][0]["row"] == 1

    calendar = await _calendar(client, admin, sy)
    assert len(calendar["classes"]) == 1  # solo la original
    assert calendar["activities"] == []  # la actividad tampoco se creó


async def test_resend_same_load_conflicts(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    assert (
        await _bulk(client, admin, sy, classes=[_class()])
    ).status_code == 201
    r = await _bulk(client, admin, sy, classes=[_class()])
    assert r.status_code == 409
    calendar = await _calendar(client, admin, sy)
    assert len(calendar["classes"]) == 1


async def test_activities_may_share_hour_with_classes(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    r = await _bulk(
        client,
        admin,
        sy,
        classes=[_class()],
        activities=[_activity(due_date="2026-03-03", due_time="18:30")],
    )
    assert r.status_code == 201, r.text
    calendar = await _calendar(client, admin, sy)
    assert len(calendar["classes"]) == 1 and len(calendar["activities"]) == 1
