from tests.helpers import STUDENT, SUPER_ADMIN, section_year

URL = "/student-section-years"
ANA, LUIS = 1, 2  # ids de los alumnos del seed


async def _section_id(client, headers, id_section_year: int) -> int:
    r = await client.get(f"/section-years/{id_section_year}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id_section"]


async def _enroll(client, headers, id_student: int, id_section_year: int) -> dict:
    r = await client.post(
        URL,
        json={"id_student": id_student, "id_section_year": id_section_year},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _pair(id_student: int, id_section_year: int) -> dict:
    return {"id_student": id_student, "id_section_year": id_section_year}


# ---------- permisos ----------
async def test_requires_authentication(client):
    assert (await client.get(URL)).status_code == 401
    assert (await client.get(f"{URL}/1")).status_code == 401
    assert (await client.post(URL, json=_pair(ANA, 1))).status_code == 401
    assert (await client.patch(f"{URL}/1", json={"id_student": ANA})).status_code == 401
    assert (await client.delete(f"{URL}/1")).status_code == 401


async def test_student_cannot_read_or_write(client, login):
    headers = await login(STUDENT)
    assert (await client.get(URL, headers=headers)).status_code == 403
    assert (await client.get(f"{URL}/1", headers=headers)).status_code == 403
    assert (await client.post(URL, json=_pair(ANA, 1), headers=headers)).status_code == 403
    assert (await client.patch(f"{URL}/1", json={"id_student": ANA}, headers=headers)).status_code == 403
    assert (await client.delete(f"{URL}/1", headers=headers)).status_code == 403


async def test_regular_professor_can_read_but_not_write(client, login, make_professor):
    headers = await login(await make_professor("prof-cursadas@frc.utn.edu.ar"))
    assert (await client.get(URL, headers=headers)).status_code == 200
    assert (await client.post(URL, json=_pair(ANA, 1), headers=headers)).status_code == 403


# ---------- crear ----------
async def test_create_enrollment(client, login):
    headers = await login(SUPER_ADMIN)
    sy = await section_year(client, headers)
    r = await client.post(URL, json=_pair(ANA, sy), headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id_student"] == ANA
    assert body["student_first_name"] == "Ana"
    assert body["student_last_name"] == "Gómez"
    assert body["student_legajo"] == 100001
    assert body["id_section_year"] == sy
    assert body["year"] == 2025
    assert body["section_name"] == "3K1"
    assert body["id_section"] == await _section_id(client, headers, sy)


async def test_create_duplicate_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    sy = await section_year(client, headers)
    await _enroll(client, headers, ANA, sy)
    r = await client.post(URL, json=_pair(ANA, sy), headers=headers)
    assert r.status_code == 409


async def test_create_unknown_references(client, login):
    headers = await login(SUPER_ADMIN)
    sy = await section_year(client, headers)
    assert (await client.post(URL, json=_pair(999, sy), headers=headers)).status_code == 404
    assert (await client.post(URL, json=_pair(ANA, 999), headers=headers)).status_code == 404


async def test_create_invalid_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    for body in (
        {},
        {"id_student": ANA},
        {"id_section_year": 1},
        {"id_student": 0, "id_section_year": 1},
        {**_pair(ANA, 1), "id_student_section_year": 1},
    ):
        r = await client.post(URL, json=body, headers=headers)
        assert r.status_code == 422, body


async def test_many_to_many(client, login):
    headers = await login(SUPER_ADMIN)
    sy_2025 = await section_year(client, headers, "3K1", 2025)
    sy_2026 = await section_year(client, headers, "3K2", 2026)
    await _enroll(client, headers, ANA, sy_2025)
    await _enroll(client, headers, ANA, sy_2026)  # misma alumna, dos años
    await _enroll(client, headers, LUIS, sy_2025)  # mismo curso, dos alumnos
    by_student = (await client.get(URL, params={"id_student": ANA}, headers=headers)).json()
    assert by_student["total"] == 2
    by_section = (await client.get(URL, params={"id_section_year": sy_2025}, headers=headers)).json()
    assert by_section["total"] == 2


# ---------- consultar ----------
async def test_list_ordering(client, login):
    headers = await login(SUPER_ADMIN)
    sy_2025 = await section_year(client, headers, "3K1", 2025)
    sy_2024 = await section_year(client, headers, "3K2", 2024)
    await _enroll(client, headers, ANA, sy_2025)
    await _enroll(client, headers, LUIS, sy_2025)
    await _enroll(client, headers, ANA, sy_2024)
    items = (await client.get(URL, headers=headers)).json()["items"]
    assert [(i["year"], i["student_last_name"]) for i in items] == [
        (2025, "Gómez"),
        (2025, "Pérez"),
        (2024, "Gómez"),
    ]


async def test_list_filters(client, login):
    headers = await login(SUPER_ADMIN)
    sy_2025 = await section_year(client, headers, "3K1", 2025)
    sy_2024 = await section_year(client, headers, "3K2", 2024)
    await _enroll(client, headers, ANA, sy_2025)
    await _enroll(client, headers, LUIS, sy_2024)
    id_section = await _section_id(client, headers, sy_2024)
    assert (await client.get(URL, params={"year": 2024}, headers=headers)).json()["total"] == 1
    assert (await client.get(URL, params={"id_section": id_section}, headers=headers)).json()["total"] == 1
    assert (
        await client.get(
            URL, params={"id_student": ANA, "id_section_year": sy_2025}, headers=headers
        )
    ).json()["total"] == 1
    assert (
        await client.get(
            URL, params={"id_student": ANA, "id_section_year": sy_2024}, headers=headers
        )
    ).json()["total"] == 0


async def test_list_pagination(client, login):
    headers = await login(SUPER_ADMIN)
    sy_2025 = await section_year(client, headers, "3K1", 2025)
    await _enroll(client, headers, ANA, sy_2025)
    await _enroll(client, headers, LUIS, sy_2025)
    page = (await client.get(URL, params={"limit": 1}, headers=headers)).json()
    assert len(page["items"]) == 1 and page["total"] == 2
    page2 = (await client.get(URL, params={"limit": 1, "offset": 1}, headers=headers)).json()
    assert len(page2["items"]) == 1
    assert (await client.get(URL, params={"limit": 0}, headers=headers)).status_code == 422


async def test_get_by_id_and_not_found(client, login):
    headers = await login(SUPER_ADMIN)
    sy = await section_year(client, headers)
    created = await _enroll(client, headers, ANA, sy)
    student = await login(STUDENT)  # un alumno no puede leer
    assert (await client.get(f"{URL}/{created['id_student_section_year']}", headers=student)).status_code == 403
    got = await client.get(f"{URL}/{created['id_student_section_year']}", headers=headers)
    assert got.status_code == 200 and got.json() == created
    assert (await client.get(f"{URL}/999", headers=headers)).status_code == 404


async def test_list_does_not_expose_private_data(client, login):
    headers = await login(SUPER_ADMIN)
    sy = await section_year(client, headers)
    created = await _enroll(client, headers, ANA, sy)
    assert set(created) == {
        "id_student_section_year",
        "id_student",
        "student_first_name",
        "student_last_name",
        "student_legajo",
        "id_section_year",
        "year",
        "id_section",
        "section_name",
    }


# ---------- modificar ----------
async def test_patch_each_side(client, login):
    headers = await login(SUPER_ADMIN)
    sy_2025 = await section_year(client, headers, "3K1", 2025)
    sy_2026 = await section_year(client, headers, "3K2", 2026)
    created = await _enroll(client, headers, ANA, sy_2025)
    url = f"{URL}/{created['id_student_section_year']}"
    r = await client.patch(url, json={"id_student": LUIS}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["id_student"] == LUIS and r.json()["year"] == 2025
    r = await client.patch(url, json={"id_section_year": sy_2026}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["id_section_year"] == sy_2026


async def test_patch_same_values_is_ok(client, login):
    headers = await login(SUPER_ADMIN)
    sy = await section_year(client, headers)
    created = await _enroll(client, headers, ANA, sy)
    r = await client.patch(
        f"{URL}/{created['id_student_section_year']}", json=_pair(ANA, sy), headers=headers
    )
    assert r.status_code == 200 and r.json() == created


async def test_patch_duplicate_pair_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    sy = await section_year(client, headers)
    first = await _enroll(client, headers, ANA, sy)
    second = await _enroll(client, headers, LUIS, sy)
    r = await client.patch(
        f"{URL}/{second['id_student_section_year']}", json={"id_student": ANA}, headers=headers
    )
    assert r.status_code == 409


async def test_patch_invalid_and_not_found(client, login):
    headers = await login(SUPER_ADMIN)
    sy = await section_year(client, headers)
    created = await _enroll(client, headers, ANA, sy)
    url = f"{URL}/{created['id_student_section_year']}"
    assert (await client.patch(url, json={}, headers=headers)).status_code == 422
    assert (await client.patch(url, json={"otro": 1}, headers=headers)).status_code == 422
    assert (await client.patch(url, json={"id_student": 999}, headers=headers)).status_code == 404
    assert (await client.patch(url, json={"id_section_year": 999}, headers=headers)).status_code == 404
    assert (await client.patch(f"{URL}/999", json={"id_student": ANA}, headers=headers)).status_code == 404


# ---------- eliminar ----------
async def test_delete_enrollment(client, login):
    headers = await login(SUPER_ADMIN)
    sy = await section_year(client, headers)
    created = await _enroll(client, headers, ANA, sy)
    r = await client.delete(f"{URL}/{created['id_student_section_year']}", headers=headers)
    assert r.status_code == 204
    assert (await client.get(f"{URL}/{created['id_student_section_year']}", headers=headers)).status_code == 404
    # los dos lados siguen existiendo
    assert (await client.get("/section-years/" + str(sy), headers=headers)).status_code == 200
    listing = await client.get("/students", params={"q": "100001"}, headers=headers)
    assert listing.json()["total"] == 1


async def test_delete_not_found(client, login):
    assert (await client.delete(f"{URL}/999", headers=await login(SUPER_ADMIN))).status_code == 404
