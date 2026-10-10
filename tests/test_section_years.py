from tests.helpers import STUDENT, SUPER_ADMIN

ENDPOINTS = [
    ("POST", "/section-years", {"year": 2025, "id_section": 1}),
    ("GET", "/section-years", None),
    ("GET", "/section-years/1", None),
    ("PATCH", "/section-years/1", {"year": 2024}),
    ("DELETE", "/section-years/1", None),
]


async def _section(client, headers, name: str) -> int:
    r = await client.post("/sections", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id_section"]


async def _create(client, headers, id_section: int, year: int) -> dict:
    r = await client.post(
        "/section-years", json={"year": year, "id_section": id_section}, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------- permisos ----------
async def test_requires_authentication(client):
    for method, url, body in ENDPOINTS:
        r = await client.request(method, url, json=body)
        assert r.status_code == 401, (method, url)


async def test_student_cannot_manage_section_years(client, login):
    headers = await login(STUDENT)
    for method, url, body in ENDPOINTS:
        r = await client.request(method, url, json=body, headers=headers)
        assert r.status_code == 403, (method, url)


async def test_regular_professor_cannot_manage_section_years(client, login, make_professor):
    headers = await login(await make_professor("prof@frc.utn.edu.ar"))
    for method, url, body in ENDPOINTS:
        r = await client.request(method, url, json=body, headers=headers)
        assert r.status_code == 403, (method, url)


# ---------- crear ----------
async def test_create_section_year(client, login):
    headers = await login(SUPER_ADMIN)
    id_section = await _section(client, headers, "3K1")
    created = await _create(client, headers, id_section, 2021)
    assert created["year"] == 2021
    assert created["id_section"] == id_section
    assert created["section_name"] == "3K1"
    assert created["id_section_year"]


async def test_create_duplicate_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    id_section = await _section(client, headers, "3K1")
    await _create(client, headers, id_section, 2025)
    r = await client.post(
        "/section-years", json={"year": 2025, "id_section": id_section}, headers=headers
    )
    assert r.status_code == 409


async def test_same_section_other_year_and_same_year_other_section_are_ok(client, login):
    headers = await login(SUPER_ADMIN)
    k1 = await _section(client, headers, "3K1")
    k2 = await _section(client, headers, "3K2")
    await _create(client, headers, k1, 2025)
    await _create(client, headers, k1, 2026)  # misma comisión, otro año
    await _create(client, headers, k2, 2025)  # mismo año, otra comisión


async def test_create_unknown_section_rejected(client, login):
    r = await client.post(
        "/section-years", json={"year": 2025, "id_section": 999}, headers=await login(SUPER_ADMIN)
    )
    assert r.status_code == 404


async def test_create_invalid_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    id_section = await _section(client, headers, "3K1")
    for body in (
        {"year": 1999, "id_section": id_section},
        {"year": 2101, "id_section": id_section},
        {"year": 2025},
        {"id_section": id_section},
        {"year": 2025, "id_section": 0},
        {"year": 2025, "id_section": id_section, "extra": 1},
    ):
        r = await client.post("/section-years", json=body, headers=headers)
        assert r.status_code == 422, body


# ---------- consultar ----------
async def test_list_sorted_by_year_desc_then_section(client, login):
    headers = await login(SUPER_ADMIN)
    k1 = await _section(client, headers, "3K1")
    k2 = await _section(client, headers, "3K2")
    await _create(client, headers, k2, 2025)
    await _create(client, headers, k1, 2021)
    await _create(client, headers, k1, 2025)
    body = (await client.get("/section-years", headers=headers)).json()
    assert body["total"] == 3
    assert [(i["year"], i["section_name"]) for i in body["items"]] == [
        (2025, "3K1"),
        (2025, "3K2"),
        (2021, "3K1"),
    ]


async def test_list_filters_and_pagination(client, login):
    headers = await login(SUPER_ADMIN)
    k1 = await _section(client, headers, "3K1")
    k2 = await _section(client, headers, "3K2")
    await _create(client, headers, k1, 2024)
    await _create(client, headers, k1, 2025)
    await _create(client, headers, k2, 2025)
    by_year = (await client.get("/section-years?year=2025", headers=headers)).json()
    assert by_year["total"] == 2
    by_section = (await client.get(f"/section-years?id_section={k1}", headers=headers)).json()
    assert by_section["total"] == 2
    both = (await client.get(f"/section-years?year=2025&id_section={k2}", headers=headers)).json()
    assert [i["section_name"] for i in both["items"]] == ["3K2"]
    page1 = (await client.get("/section-years?limit=2", headers=headers)).json()
    assert len(page1["items"]) == 2 and page1["total"] == 3
    page2 = (await client.get("/section-years?limit=2&offset=2", headers=headers)).json()
    assert len(page2["items"]) == 1
    assert (await client.get("/section-years?limit=0", headers=headers)).status_code == 422


async def test_get_section_year(client, login):
    headers = await login(SUPER_ADMIN)
    created = await _create(client, headers, await _section(client, headers, "3K1"), 2025)
    r = await client.get(f"/section-years/{created['id_section_year']}", headers=headers)
    assert r.status_code == 200
    assert r.json() == created


async def test_get_not_found(client, login):
    r = await client.get("/section-years/999", headers=await login(SUPER_ADMIN))
    assert r.status_code == 404


# ---------- modificar ----------
async def test_patch_year(client, login):
    headers = await login(SUPER_ADMIN)
    created = await _create(client, headers, await _section(client, headers, "3K1"), 2025)
    r = await client.patch(
        f"/section-years/{created['id_section_year']}", json={"year": 2024}, headers=headers
    )
    assert r.status_code == 200
    assert r.json()["year"] == 2024
    assert r.json()["section_name"] == "3K1"


async def test_patch_section(client, login):
    headers = await login(SUPER_ADMIN)
    k1 = await _section(client, headers, "3K1")
    k2 = await _section(client, headers, "3K2")
    created = await _create(client, headers, k1, 2025)
    r = await client.patch(
        f"/section-years/{created['id_section_year']}", json={"id_section": k2}, headers=headers
    )
    assert r.status_code == 200
    assert (r.json()["id_section"], r.json()["section_name"], r.json()["year"]) == (k2, "3K2", 2025)
    again = await client.get(f"/section-years/{created['id_section_year']}", headers=headers)
    assert again.json()["section_name"] == "3K2"


async def test_patch_to_existing_combination_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    k1 = await _section(client, headers, "3K1")
    await _create(client, headers, k1, 2025)
    other = await _create(client, headers, k1, 2024)
    r = await client.patch(
        f"/section-years/{other['id_section_year']}", json={"year": 2025}, headers=headers
    )
    assert r.status_code == 409


async def test_patch_same_values_is_ok(client, login):
    headers = await login(SUPER_ADMIN)
    k1 = await _section(client, headers, "3K1")
    created = await _create(client, headers, k1, 2025)
    r = await client.patch(
        f"/section-years/{created['id_section_year']}",
        json={"year": 2025, "id_section": k1},
        headers=headers,
    )
    assert r.status_code == 200


async def test_patch_not_found(client, login):
    r = await client.patch("/section-years/999", json={"year": 2024}, headers=await login(SUPER_ADMIN))
    assert r.status_code == 404


async def test_patch_unknown_section_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    created = await _create(client, headers, await _section(client, headers, "3K1"), 2025)
    r = await client.patch(
        f"/section-years/{created['id_section_year']}", json={"id_section": 999}, headers=headers
    )
    assert r.status_code == 404


async def test_patch_invalid_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    created = await _create(client, headers, await _section(client, headers, "3K1"), 2025)
    url = f"/section-years/{created['id_section_year']}"
    for body in ({}, {"year": 1999}, {"year": 2101}, {"id_section": 0}, {"year": 2024, "extra": 1}):
        r = await client.patch(url, json=body, headers=headers)
        assert r.status_code == 422, body


# ---------- eliminar ----------
async def test_delete_section_year(client, login):
    headers = await login(SUPER_ADMIN)
    created = await _create(client, headers, await _section(client, headers, "3K1"), 2025)
    url = f"/section-years/{created['id_section_year']}"
    assert (await client.delete(url, headers=headers)).status_code == 204
    assert (await client.get(url, headers=headers)).status_code == 404
    assert (await client.get("/section-years", headers=headers)).json()["total"] == 0


async def test_delete_not_found(client, login):
    r = await client.delete("/section-years/999", headers=await login(SUPER_ADMIN))
    assert r.status_code == 404


async def test_cannot_delete_section_in_use(client, login):
    headers = await login(SUPER_ADMIN)
    id_section = await _section(client, headers, "3K1")
    created = await _create(client, headers, id_section, 2025)
    assert (await client.delete(f"/sections/{id_section}", headers=headers)).status_code == 409
    # al eliminar su curso lectivo, la comisión ya se puede borrar
    await client.delete(f"/section-years/{created['id_section_year']}", headers=headers)
    assert (await client.delete(f"/sections/{id_section}", headers=headers)).status_code == 204


async def test_deleted_combination_can_be_reused(client, login):
    headers = await login(SUPER_ADMIN)
    id_section = await _section(client, headers, "3K1")
    created = await _create(client, headers, id_section, 2025)
    await client.delete(f"/section-years/{created['id_section_year']}", headers=headers)
    await _create(client, headers, id_section, 2025)