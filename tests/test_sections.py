from tests.helpers import STUDENT, SUPER_ADMIN

READ = [
    ("GET", "/sections", None),
    ("GET", "/sections/1", None),
]
WRITE = [
    ("POST", "/sections", {"name": "3K1"}),
    ("PATCH", "/sections/1", {"name": "3K2"}),
    ("DELETE", "/sections/1", None),
]
ENDPOINTS = READ + WRITE


async def _create(client, headers, name: str) -> dict:
    r = await client.post("/sections", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ---------- permisos ----------
async def test_requires_authentication(client):
    for method, url, body in ENDPOINTS:
        r = await client.request(method, url, json=body)
        assert r.status_code == 401, (method, url)


async def test_student_cannot_write_sections(client, login):
    headers = await login(STUDENT)
    for method, url, body in WRITE:
        r = await client.request(method, url, json=body, headers=headers)
        assert r.status_code == 403, (method, url)


async def test_regular_professor_cannot_write_sections(client, login, make_professor):
    headers = await login(await make_professor("prof@frc.utn.edu.ar"))
    for method, url, body in WRITE:
        r = await client.request(method, url, json=body, headers=headers)
        assert r.status_code == 403, (method, url)


async def test_any_user_can_read_sections(client, login, make_professor):
    created = await _create(client, await login(SUPER_ADMIN), "3K1")
    professor = await login(await make_professor("prof@frc.utn.edu.ar"))
    for headers in (await login(STUDENT), professor):
        listing = await client.get("/sections", headers=headers)
        assert listing.status_code == 200 and listing.json()["total"] == 1
        one = await client.get(f"/sections/{created['id_section']}", headers=headers)
        assert one.status_code == 200 and one.json() == created


# ---------- crear ----------
async def test_create_section_normalizes_name(client, login):
    r = await client.post("/sections", json={"name": "  3k1 "}, headers=await login(SUPER_ADMIN))
    assert r.status_code == 201
    assert r.json()["name"] == "3K1"
    assert r.json()["id_section"]


async def test_create_duplicate_name_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    await _create(client, headers, "3K1")
    for name in ("3K1", "3k1"):
        r = await client.post("/sections", json={"name": name}, headers=headers)
        assert r.status_code == 409, name


async def test_create_invalid_name_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    for body in ({"name": ""}, {"name": "   "}, {"name": "A" * 21}, {}, {"name": "3K1", "id_section": 5}):
        r = await client.post("/sections", json=body, headers=headers)
        assert r.status_code == 422, body


# ---------- consultar ----------
async def test_list_sections_sorted_by_name(client, login):
    headers = await login(SUPER_ADMIN)
    for name in ("3K2", "4K1", "3K1"):
        await _create(client, headers, name)
    body = (await client.get("/sections", headers=headers)).json()
    assert body["total"] == 3
    assert [s["name"] for s in body["items"]] == ["3K1", "3K2", "4K1"]


async def test_list_search_and_pagination(client, login):
    headers = await login(SUPER_ADMIN)
    for name in ("3K1", "3K2", "4K1"):
        await _create(client, headers, name)
    found = (await client.get("/sections?q=3k", headers=headers)).json()
    assert [s["name"] for s in found["items"]] == ["3K1", "3K2"]
    page1 = (await client.get("/sections?limit=2", headers=headers)).json()
    assert len(page1["items"]) == 2 and page1["total"] == 3
    page2 = (await client.get("/sections?limit=2&offset=2", headers=headers)).json()
    assert len(page2["items"]) == 1
    assert (await client.get("/sections?limit=0", headers=headers)).status_code == 422


async def test_get_section(client, login):
    headers = await login(SUPER_ADMIN)
    created = await _create(client, headers, "3K1")
    r = await client.get(f"/sections/{created['id_section']}", headers=headers)
    assert r.status_code == 200
    assert r.json() == created


async def test_get_section_not_found(client, login):
    r = await client.get("/sections/999", headers=await login(SUPER_ADMIN))
    assert r.status_code == 404


# ---------- modificar ----------
async def test_rename_section(client, login):
    headers = await login(SUPER_ADMIN)
    created = await _create(client, headers, "3K1")
    r = await client.patch(
        f"/sections/{created['id_section']}", json={"name": "3k3"}, headers=headers
    )
    assert r.status_code == 200
    assert r.json() == {"id_section": created["id_section"], "name": "3K3"}
    assert (await client.get(f"/sections/{created['id_section']}", headers=headers)).json()["name"] == "3K3"


async def test_rename_same_name_is_ok(client, login):
    headers = await login(SUPER_ADMIN)
    created = await _create(client, headers, "3K1")
    r = await client.patch(
        f"/sections/{created['id_section']}", json={"name": "3k1"}, headers=headers
    )
    assert r.status_code == 200


async def test_rename_to_existing_name_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    await _create(client, headers, "3K1")
    other = await _create(client, headers, "3K2")
    r = await client.patch(
        f"/sections/{other['id_section']}", json={"name": "3k1"}, headers=headers
    )
    assert r.status_code == 409


async def test_patch_section_not_found(client, login):
    r = await client.patch("/sections/999", json={"name": "3K1"}, headers=await login(SUPER_ADMIN))
    assert r.status_code == 404


async def test_patch_invalid_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    created = await _create(client, headers, "3K1")
    url = f"/sections/{created['id_section']}"
    for body in ({}, {"name": ""}, {"name": "A" * 21}, {"name": "3K2", "id_section": 9}):
        r = await client.patch(url, json=body, headers=headers)
        assert r.status_code == 422, body


# ---------- eliminar ----------
async def test_delete_section(client, login):
    headers = await login(SUPER_ADMIN)
    created = await _create(client, headers, "3K1")
    url = f"/sections/{created['id_section']}"
    assert (await client.delete(url, headers=headers)).status_code == 204
    assert (await client.get(url, headers=headers)).status_code == 404
    assert (await client.get("/sections", headers=headers)).json()["total"] == 0


async def test_delete_not_found(client, login):
    r = await client.delete("/sections/999", headers=await login(SUPER_ADMIN))
    assert r.status_code == 404


async def test_deleted_name_can_be_reused(client, login):
    headers = await login(SUPER_ADMIN)
    created = await _create(client, headers, "3K1")
    await client.delete(f"/sections/{created['id_section']}", headers=headers)
    await _create(client, headers, "3K1")