from tests.helpers import STUDENT, SUPER_ADMIN

URL = "/technologies"

READ = [("GET", URL, None), ("GET", f"{URL}/1", None)]
WRITE = [
    ("POST", URL, {"name": "A"}),
    ("PATCH", f"{URL}/1", {"name": "B"}),
    ("DELETE", f"{URL}/1", None),
]
ENDPOINTS = READ + WRITE


async def _create(client, headers, name: str, description: str | None = None) -> dict:
    r = await client.post(URL, json={"name": name, "description": description}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def _section_year(client, headers) -> int:
    r = await client.post("/sections", json={"name": "3K1"}, headers=headers)
    assert r.status_code == 201, r.text
    r = await client.post(
        "/section-years",
        json={"year": 2025, "id_section": r.json()["id_section"], "min_students": 1, "max_students": 10},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id_section_year"]


async def _link(client, headers, id_project: int, id_technology: int) -> None:
    r = await client.post(
        f"/projects/{id_project}/technologies", json={"id_technology": id_technology}, headers=headers
    )
    assert r.status_code == 201, r.text


# ---------- permisos ----------
async def test_requires_authentication(client):
    for method, url, body in ENDPOINTS:
        r = await client.request(method, url, json=body)
        assert r.status_code == 401, (method, url)


async def test_student_cannot_write(client, login):
    headers = await login(STUDENT)
    for method, url, body in WRITE:
        r = await client.request(method, url, json=body, headers=headers)
        assert r.status_code == 403, (method, url)


async def test_regular_professor_can_write(client, login, make_professor):
    headers = await login(await make_professor("prof-tech@frc.utn.edu.ar"))
    created = await _create(client, headers, "React")
    r = await client.patch(f"{URL}/{created['id_technology']}", json={"name": "Vue"}, headers=headers)
    assert r.status_code == 200, r.text
    assert (await client.delete(f"{URL}/{created['id_technology']}", headers=headers)).status_code == 204


async def test_any_user_can_read(client, login):
    created = await _create(client, await login(SUPER_ADMIN), "React", "Una biblioteca")
    headers = await login(STUDENT)
    listed = (await client.get(URL, headers=headers)).json()
    assert listed["total"] == 1
    one = await client.get(f"{URL}/{created['id_technology']}", headers=headers)
    assert one.status_code == 200 and one.json() == created


# ---------- crear ----------
async def test_create_technology(client, login):
    headers = await login(SUPER_ADMIN)
    body = await _create(client, headers, "  React  ", "A JS library")
    assert body["name"] == "React"
    assert body["description"] == "A JS library"


async def test_create_without_description(client, login):
    headers = await login(SUPER_ADMIN)
    r = await client.post(URL, json={"name": "React"}, headers=headers)
    assert r.status_code == 201 and r.json()["description"] is None, r.text


async def test_create_duplicate_case_insensitive(client, login):
    headers = await login(SUPER_ADMIN)
    await _create(client, headers, "React")
    for name in ("react", "REACT", "ReAct"):
        r = await client.post(URL, json={"name": name}, headers=headers)
        assert r.status_code == 409, name


async def test_create_invalid_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    for body in ({}, {"name": ""}, {"name": "a" * 101}, {"name": "a", "description": "x" * 501},
                 {"name": "a", "extra": 1}):
        r = await client.post(URL, json=body, headers=headers)
        assert r.status_code == 422, body


# ---------- consultar ----------
async def test_list_ordered_by_name(client, login):
    headers = await login(SUPER_ADMIN)
    await _create(client, headers, "Vue")
    await _create(client, headers, "Angular")
    await _create(client, headers, "React")
    body = (await client.get(URL, headers=headers)).json()
    assert [t["name"] for t in body["items"]] == ["Angular", "React", "Vue"]
    assert body["total"] == 3


async def test_list_q_filter(client, login):
    headers = await login(SUPER_ADMIN)
    react = await _create(client, headers, "React")
    await _create(client, headers, "Redux")
    await _create(client, headers, "Vue")
    body = (await client.get(f"{URL}?q=rea", headers=headers)).json()
    assert body["total"] == 1 and body["items"][0]["id_technology"] == react["id_technology"]
    body = (await client.get(f"{URL}?q=reac", headers=headers)).json()
    assert body["total"] == 1


async def test_list_pagination(client, login):
    headers = await login(SUPER_ADMIN)
    for name in ("Angular", "React", "Vue"):
        await _create(client, headers, name)
    page1 = (await client.get(f"{URL}?limit=2", headers=headers)).json()
    assert len(page1["items"]) == 2 and page1["total"] == 3
    page2 = (await client.get(f"{URL}?limit=2&offset=2", headers=headers)).json()
    assert len(page2["items"]) == 1
    assert (await client.get(f"{URL}?limit=0", headers=headers)).status_code == 422


async def test_get_not_found(client, login):
    assert (await client.get(f"{URL}/999", headers=await login(SUPER_ADMIN))).status_code == 404


# ---------- modificar ----------
async def test_patch_name_and_description(client, login):
    headers = await login(SUPER_ADMIN)
    created = await _create(client, headers, "react", "Desc")
    r = await client.patch(
        f"{URL}/{created['id_technology']}", json={"name": "React", "description": "New"}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "React" and r.json()["description"] == "New"


async def test_patch_clear_description(client, login):
    headers = await login(SUPER_ADMIN)
    created = await _create(client, headers, "React", "Desc")
    r = await client.patch(f"{URL}/{created['id_technology']}", json={"description": None}, headers=headers)
    assert r.status_code == 200 and r.json()["description"] is None, r.text


async def test_patch_name_null_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    created = await _create(client, headers, "React")
    r = await client.patch(f"{URL}/{created['id_technology']}", json={"name": None}, headers=headers)
    assert r.status_code == 422


async def test_patch_empty_and_unknown_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    created = await _create(client, headers, "React")
    for body in ({}, {"extra": 1}, {"description": "x" * 501}):
        url = f"{URL}/{created['id_technology']}"
        r = await client.patch(url, json=body, headers=headers)
        assert r.status_code == 422, body


async def test_patch_duplicate_name_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    await _create(client, headers, "Angular")
    other = await _create(client, headers, "React")
    r = await client.patch(f"{URL}/{other['id_technology']}", json={"name": "angular"}, headers=headers)
    assert r.status_code == 409


async def test_patch_not_found(client, login):
    assert (await client.patch(f"{URL}/999", json={"name": "B"}, headers=await login(SUPER_ADMIN))).status_code == 404


# ---------- eliminar ----------
async def test_delete_technology(client, login):
    headers = await login(SUPER_ADMIN)
    created = await _create(client, headers, "React")
    url = f"{URL}/{created['id_technology']}"
    assert (await client.delete(url, headers=headers)).status_code == 204
    assert (await client.get(url, headers=headers)).status_code == 404


async def test_delete_not_found(client, login):
    assert (await client.delete(f"{URL}/999", headers=await login(SUPER_ADMIN))).status_code == 404


async def test_delete_in_use_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    created = await _create(client, headers, "React")
    id_technology = created["id_technology"]
    sy = await _section_year(client, headers)
    r = await client.post("/projects", json={"id_section_year": sy}, headers=headers)
    assert r.status_code == 201, r.text
    await _link(client, headers, r.json()["id_project"], id_technology)
    r = await client.delete(f"{URL}/{id_technology}", headers=headers)
    assert r.status_code == 409, r.text
    assert (await client.get(f"{URL}/{id_technology}", headers=headers)).status_code == 200
