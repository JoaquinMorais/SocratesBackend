from tests.helpers import STUDENT, SUPER_ADMIN, assign_professor, section_year

URL = "/section-years"
ITEM = "/activities"
ANA_ID = 1
LUIS = "100002@sistemas.frc.utn.edu.ar"


def _body(**overrides) -> dict:
    return {
        "title": "Entrega del informe",
        "description": "Documento con el avance.",
        "due_date": "2026-05-15",
        "due_time": "23:59",
        **overrides,
    }


async def _sy(client, headers, name: str = "3K1", year: int = 2026) -> int:
    return await section_year(client, headers, name, year)


async def _create(client, headers, id_section_year: int, **overrides) -> dict:
    r = await client.post(
        f"{URL}/{id_section_year}/activities",
        json=_body(**overrides),
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
    assert (await client.get(f"{URL}/1/activities")).status_code == 401
    assert (
        await client.post(f"{URL}/1/activities", json=_body())
    ).status_code == 401
    assert (await client.get(f"{ITEM}/1")).status_code == 401
    assert (await client.patch(f"{ITEM}/1", json={"title": "X"})).status_code == 401
    assert (await client.delete(f"{ITEM}/1")).status_code == 401


async def test_student_of_other_course_forbidden(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    activity = await _create(client, admin, sy)
    headers = await login(STUDENT)  # Ana no cursa ese curso

    assert (await client.get(f"{URL}/{sy}/activities", headers=headers)).status_code == 403
    assert (await client.get(f"{ITEM}/{activity['id_activity']}", headers=headers)).status_code == 403
    assert (
        await client.post(f"{URL}/{sy}/activities", json=_body(), headers=headers)
    ).status_code == 403


async def test_enrolled_student_can_read_but_not_write(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    await _create(client, admin, sy)
    await _enroll(client, admin, ANA_ID, sy)
    headers = await login(STUDENT)

    assert (await client.get(f"{URL}/{sy}/activities", headers=headers)).status_code == 200
    assert (
        await client.post(f"{URL}/{sy}/activities", json=_body(), headers=headers)
    ).status_code == 403


async def test_member_of_project_can_read(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    await _create(client, admin, sy)
    lu = await login(LUIS)
    await _join_project(client, admin, lu, sy)

    assert (await client.get(f"{URL}/{sy}/activities", headers=lu)).status_code == 200


async def test_assigned_professor_manages_and_other_cannot(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    assigned = await make_professor("prof-act@frc.utn.edu.ar")
    other = await make_professor("prof-act-otro@frc.utn.edu.ar", legajo=300001)
    await assign_professor(client, admin, assigned, sy)

    assigned_headers = await login(assigned)
    activity = await _create(client, assigned_headers, sy)
    assert (await client.get(f"{URL}/{sy}/activities", headers=assigned_headers)).status_code == 200
    r = await client.patch(
        f"{ITEM}/{activity['id_activity']}", json={"title": "Otro título"}, headers=assigned_headers
    )
    assert r.status_code == 200, r.text
    assert (await client.delete(f"{ITEM}/{activity['id_activity']}", headers=assigned_headers)).status_code == 204

    other_headers = await login(other)
    created = await _create(client, admin, sy)
    assert (await client.get(f"{URL}/{sy}/activities", headers=other_headers)).status_code == 403
    assert (await client.get(f"{ITEM}/{created['id_activity']}", headers=other_headers)).status_code == 403
    assert (
        await client.post(f"{URL}/{sy}/activities", json=_body(), headers=other_headers)
    ).status_code == 403


async def test_super_admin_manages_any_course(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    activity = await _create(client, admin, sy)
    assert (await client.delete(f"{ITEM}/{activity['id_activity']}", headers=admin)).status_code == 204


# ---------- crear ----------
async def test_create_activity(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    created = await _create(client, admin, sy)
    assert created["id_section_year"] == sy
    assert created["title"] == "Entrega del informe"
    assert created["description"] == "Documento con el avance."
    assert created["due_date"] == "2026-05-15"
    assert created["due_time"] == "23:59:00"
    assert set(created) == {
        "id_activity",
        "id_calendar",
        "id_section_year",
        "title",
        "description",
        "due_date",
        "due_time",
    }


async def test_create_without_optional_fields(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    created = await _create(client, admin, sy, description=None, due_time=None)
    assert created["description"] is None and created["due_time"] is None


async def test_create_validation(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    invalid = [
        _body(title="   "),
        _body(title="x" * 201),
        _body(due_date="2027-05-15"),  # fuera del año del curso
        _body(due_time="25:00"),
        _body(otro=1),
        {"title": "Sin fecha"},
    ]
    for body in invalid:
        r = await client.post(f"{URL}/{sy}/activities", json=body, headers=admin)
        assert r.status_code == 422, body
    assert (
        await client.post(f"{URL}/999/activities", json=_body(), headers=admin)
    ).status_code == 404


async def test_title_is_trimmed(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    created = await _create(client, admin, sy, title="  Entrega  ")
    assert created["title"] == "Entrega"


# ---------- consultar ----------
async def test_list_ordering_filters_and_pagination(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    await _create(client, admin, sy, title="B", due_date="2026-06-10", due_time="18:00")
    await _create(client, admin, sy, title="A", due_date="2026-05-15", due_time=None)
    await _create(client, admin, sy, title="C", due_date="2026-05-15", due_time="09:00")

    listing = (await client.get(f"{URL}/{sy}/activities", headers=admin)).json()
    assert [a["title"] for a in listing["items"]] == ["C", "A", "B"]
    assert listing["total"] == 3

    filtered = (
        await client.get(
            f"{URL}/{sy}/activities",
            params={"from": "2026-05-01", "to": "2026-05-31"},
            headers=admin,
        )
    ).json()
    assert [a["title"] for a in filtered["items"]] == ["C", "A"]

    page = (
        await client.get(f"{URL}/{sy}/activities", params={"limit": 1}, headers=admin)
    ).json()
    assert len(page["items"]) == 1 and page["total"] == 3
    assert (
        await client.get(f"{URL}/{sy}/activities", params={"limit": 0}, headers=admin)
    ).status_code == 422
    assert (
        await client.get(f"{URL}/{sy}/activities", params={"from": "2026-05-01"}, headers=admin)
    ).status_code == 422
    assert (
        await client.get(
            f"{URL}/{sy}/activities",
            params={"from": "2026-06-01", "to": "2026-05-01"},
            headers=admin,
        )
    ).status_code == 422


async def test_get_not_found(client, login):
    assert (await client.get(f"{ITEM}/999", headers=await login(SUPER_ADMIN))).status_code == 404


# ---------- modificar ----------
async def test_patch_activity(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    created = await _create(client, admin, sy)
    url = f"{ITEM}/{created['id_activity']}"

    r = await client.patch(
        url,
        json={
            "title": "Entrega final",
            "description": "Nueva descripción",
            "due_date": "2026-06-20",
            "due_time": "18:30",
        },
        headers=admin,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "Entrega final"
    assert body["description"] == "Nueva descripción"
    assert body["due_date"] == "2026-06-20"
    assert body["due_time"] == "18:30:00"

    r = await client.patch(url, json={"description": None, "due_time": None}, headers=admin)
    assert r.status_code == 200
    assert r.json()["description"] is None and r.json()["due_time"] is None

    assert (await client.patch(url, json={}, headers=admin)).status_code == 422
    assert (await client.patch(url, json={"title": None}, headers=admin)).status_code == 422
    assert (await client.patch(url, json={"title": "   "}, headers=admin)).status_code == 422
    assert (await client.patch(url, json={"otro": 1}, headers=admin)).status_code == 422
    assert (
        await client.patch(url, json={"due_date": "2027-01-01"}, headers=admin)
    ).status_code == 422
    assert (await client.patch(f"{ITEM}/999", json={"title": "X"}, headers=admin)).status_code == 404


# ---------- eliminar ----------
async def test_delete_and_cascade(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    created = await _create(client, admin, sy)
    assert (await client.delete(f"{ITEM}/{created['id_activity']}", headers=admin)).status_code == 204
    assert (await client.get(f"{ITEM}/{created['id_activity']}", headers=admin)).status_code == 404
    assert (await client.delete(f"{ITEM}/{created['id_activity']}", headers=admin)).status_code == 404

    other_sy = await _sy(client, admin, "3K2", 2026)
    other = await _create(client, admin, other_sy)
    assert (await client.delete(f"{URL}/{other_sy}", headers=admin)).status_code == 204
    assert (await client.get(f"{ITEM}/{other['id_activity']}", headers=admin)).status_code == 404


async def test_item_permissions(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    activity = await _create(client, admin, sy)
    await _enroll(client, admin, ANA_ID, sy)
    assigned = await make_professor("prof-act-item@frc.utn.edu.ar")
    other = await make_professor("prof-act-item-otro@frc.utn.edu.ar", legajo=300001)
    await assign_professor(client, admin, assigned, sy)
    url = f"{ITEM}/{activity['id_activity']}"

    # alumno del curso: lee, pero no modifica
    ana = await login(STUDENT)
    assert (await client.get(url, headers=ana)).status_code == 200
    assert (await client.patch(url, json={"title": "X"}, headers=ana)).status_code == 403
    assert (await client.delete(url, headers=ana)).status_code == 403

    # alumno de otro curso: no puede leer
    assert (await client.get(url, headers=await login(LUIS))).status_code == 403

    # profesor asignado: gestiona
    assigned_headers = await login(assigned)
    assert (await client.get(url, headers=assigned_headers)).status_code == 200
    assert (
        await client.patch(url, json={"title": "Editada"}, headers=assigned_headers)
    ).status_code == 200
    assert (await client.delete(url, headers=assigned_headers)).status_code == 204

    # profesor ajeno: no lee ni gestiona; la actividad sigue existiendo
    second = await _create(client, admin, sy, title="Otra")
    second_url = f"{ITEM}/{second['id_activity']}"
    other_headers = await login(other)
    assert (await client.get(second_url, headers=other_headers)).status_code == 403
    assert (
        await client.patch(second_url, json={"title": "X"}, headers=other_headers)
    ).status_code == 403
    assert (await client.delete(second_url, headers=other_headers)).status_code == 403
    assert (await client.get(second_url, headers=admin)).status_code == 200
