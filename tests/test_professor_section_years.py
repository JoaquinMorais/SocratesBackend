from tests.helpers import STUDENT, SUPER_ADMIN

URL = "/professor-section-years"
MARTA = 3  # id_professor de Marta en el seed

READ = [("GET", URL, None), ("GET", f"{URL}/1", None)]
WRITE = [
    ("POST", URL, {"id_professor": MARTA, "id_section_year": 1}),
    ("PATCH", f"{URL}/1", {"id_professor": MARTA}),
    ("DELETE", f"{URL}/1", None),
]


async def _section(client, headers, name: str) -> int:
    r = await client.post("/sections", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id_section"]


async def _section_year(client, headers, id_section: int, year: int) -> int:
    r = await client.post(
        "/section-years", json={"year": year, "id_section": id_section}, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()["id_section_year"]


async def _prof_id(client, headers, mail: str) -> int:
    r = await client.get("/users", params={"q": mail}, headers=headers)
    return r.json()["items"][0]["id_user"]


async def _assign(client, headers, id_professor: int, id_section_year: int) -> dict:
    r = await client.post(
        URL,
        json={"id_professor": id_professor, "id_section_year": id_section_year},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------- permisos ----------
async def test_requires_authentication(client):
    for method, url, body in READ + WRITE:
        r = await client.request(method, url, json=body)
        assert r.status_code == 401, (method, url)


async def test_student_cannot_write(client, login):
    headers = await login(STUDENT)
    for method, url, body in WRITE:
        r = await client.request(method, url, json=body, headers=headers)
        assert r.status_code == 403, (method, url)


async def test_regular_professor_cannot_write(client, login, make_professor):
    headers = await login(await make_professor("prof@frc.utn.edu.ar"))
    for method, url, body in WRITE:
        r = await client.request(method, url, json=body, headers=headers)
        assert r.status_code == 403, (method, url)


async def test_any_user_can_read(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sy = await _section_year(client, admin, await _section(client, admin, "3K1"), 2025)
    created = await _assign(client, admin, MARTA, sy)
    professor = await login(await make_professor("prof@frc.utn.edu.ar"))
    for headers in (await login(STUDENT), professor):
        listing = await client.get(URL, headers=headers)
        assert listing.status_code == 200 and listing.json()["total"] == 1
        one = await client.get(f"{URL}/{created['id_professor_section_year']}", headers=headers)
        assert one.status_code == 200 and one.json() == created


# ---------- crear ----------
async def test_create_assignment(client, login):
    headers = await login(SUPER_ADMIN)
    sy = await _section_year(client, headers, await _section(client, headers, "3K1"), 2025)
    created = await _assign(client, headers, MARTA, sy)
    assert created["id_professor_section_year"]
    assert created["id_professor"] == MARTA
    assert (created["professor_first_name"], created["professor_last_name"]) == ("Marta", "Rodríguez")
    assert (created["id_section_year"], created["year"], created["section_name"]) == (sy, 2025, "3K1")
    assert not {"email", "mail", "password_hash"} & created.keys()  # nada privado


async def test_create_duplicate_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    sy = await _section_year(client, headers, await _section(client, headers, "3K1"), 2025)
    await _assign(client, headers, MARTA, sy)
    r = await client.post(URL, json={"id_professor": MARTA, "id_section_year": sy}, headers=headers)
    assert r.status_code == 409


async def test_many_to_many(client, login, make_professor):
    headers = await login(SUPER_ADMIN)
    k1 = await _section(client, headers, "3K1")
    sy1 = await _section_year(client, headers, k1, 2025)
    sy2 = await _section_year(client, headers, k1, 2026)
    prof2 = await _prof_id(client, headers, await make_professor("prof@frc.utn.edu.ar"))
    await _assign(client, headers, MARTA, sy1)
    await _assign(client, headers, MARTA, sy2)  # un profesor, varios cursos lectivos
    await _assign(client, headers, prof2, sy1)  # un curso lectivo, varios profesores


async def test_create_unknown_references_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    sy = await _section_year(client, headers, await _section(client, headers, "3K1"), 2025)
    for body in (
        {"id_professor": 999, "id_section_year": sy},
        {"id_professor": 1, "id_section_year": sy},  # id 1 es una alumna, no un profesor
        {"id_professor": MARTA, "id_section_year": 999},
    ):
        r = await client.post(URL, json=body, headers=headers)
        assert r.status_code == 404, body


async def test_create_invalid_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    for body in (
        {},
        {"id_professor": MARTA},
        {"id_section_year": 1},
        {"id_professor": 0, "id_section_year": 1},
        {"id_professor": MARTA, "id_section_year": 0},
        {"id_professor": MARTA, "id_section_year": 1, "extra": 1},
    ):
        r = await client.post(URL, json=body, headers=headers)
        assert r.status_code == 422, body


# ---------- consultar ----------
async def _setup_listing(client, headers, make_professor):
    k1 = await _section(client, headers, "3K1")
    k2 = await _section(client, headers, "3K2")
    sy_a = await _section_year(client, headers, k1, 2025)
    sy_b = await _section_year(client, headers, k2, 2025)
    sy_c = await _section_year(client, headers, k1, 2024)
    prof2 = await _prof_id(client, headers, await make_professor("prof@frc.utn.edu.ar"))
    await _assign(client, headers, MARTA, sy_c)
    await _assign(client, headers, MARTA, sy_b)
    await _assign(client, headers, prof2, sy_a)
    await _assign(client, headers, MARTA, sy_a)
    return k1, sy_a, prof2


async def test_list_sorted(client, login, make_professor):
    headers = await login(SUPER_ADMIN)
    await _setup_listing(client, headers, make_professor)
    body = (await client.get(URL, headers=headers)).json()
    assert body["total"] == 4
    assert [(i["year"], i["section_name"], i["professor_last_name"]) for i in body["items"]] == [
        (2025, "3K1", "Prof"),
        (2025, "3K1", "Rodríguez"),
        (2025, "3K2", "Rodríguez"),
        (2024, "3K1", "Rodríguez"),
    ]


async def test_list_filters_and_pagination(client, login, make_professor):
    headers = await login(SUPER_ADMIN)
    k1, sy_a, prof2 = await _setup_listing(client, headers, make_professor)

    async def total(query: str) -> int:
        return (await client.get(f"{URL}?{query}", headers=headers)).json()["total"]

    assert await total(f"id_professor={MARTA}") == 3
    assert await total(f"id_professor={prof2}") == 1
    assert await total(f"id_section_year={sy_a}") == 2
    assert await total("year=2025") == 3
    assert await total(f"id_section={k1}") == 3
    assert await total(f"year=2025&id_professor={MARTA}") == 2
    page1 = (await client.get(f"{URL}?limit=3", headers=headers)).json()
    assert len(page1["items"]) == 3 and page1["total"] == 4
    page2 = (await client.get(f"{URL}?limit=3&offset=3", headers=headers)).json()
    assert len(page2["items"]) == 1
    assert (await client.get(f"{URL}?limit=0", headers=headers)).status_code == 422


async def test_get_assignment(client, login):
    headers = await login(SUPER_ADMIN)
    sy = await _section_year(client, headers, await _section(client, headers, "3K1"), 2025)
    created = await _assign(client, headers, MARTA, sy)
    r = await client.get(f"{URL}/{created['id_professor_section_year']}", headers=headers)
    assert r.status_code == 200
    assert r.json() == created


async def test_get_not_found(client, login):
    assert (await client.get(f"{URL}/999", headers=await login(SUPER_ADMIN))).status_code == 404


# ---------- modificar ----------
async def test_patch_professor(client, login, make_professor):
    headers = await login(SUPER_ADMIN)
    sy = await _section_year(client, headers, await _section(client, headers, "3K1"), 2025)
    created = await _assign(client, headers, MARTA, sy)
    prof2 = await _prof_id(client, headers, await make_professor("prof@frc.utn.edu.ar"))
    url = f"{URL}/{created['id_professor_section_year']}"
    r = await client.patch(url, json={"id_professor": prof2}, headers=headers)
    assert r.status_code == 200
    assert (r.json()["id_professor"], r.json()["professor_first_name"]) == (prof2, "Test")
    assert r.json()["id_section_year"] == sy
    assert (await client.get(url, headers=headers)).json()["id_professor"] == prof2


async def test_patch_section_year(client, login):
    headers = await login(SUPER_ADMIN)
    k1 = await _section(client, headers, "3K1")
    sy1 = await _section_year(client, headers, k1, 2025)
    sy2 = await _section_year(client, headers, k1, 2026)
    created = await _assign(client, headers, MARTA, sy1)
    url = f"{URL}/{created['id_professor_section_year']}"
    r = await client.patch(url, json={"id_section_year": sy2}, headers=headers)
    assert r.status_code == 200
    assert (r.json()["id_section_year"], r.json()["year"]) == (sy2, 2026)
    assert r.json()["id_professor"] == MARTA
    assert (await client.get(url, headers=headers)).json()["year"] == 2026


async def test_patch_to_existing_pair_rejected(client, login, make_professor):
    headers = await login(SUPER_ADMIN)
    sy = await _section_year(client, headers, await _section(client, headers, "3K1"), 2025)
    prof2 = await _prof_id(client, headers, await make_professor("prof@frc.utn.edu.ar"))
    await _assign(client, headers, MARTA, sy)
    other = await _assign(client, headers, prof2, sy)
    r = await client.patch(
        f"{URL}/{other['id_professor_section_year']}", json={"id_professor": MARTA}, headers=headers
    )
    assert r.status_code == 409


async def test_patch_same_values_is_ok(client, login):
    headers = await login(SUPER_ADMIN)
    sy = await _section_year(client, headers, await _section(client, headers, "3K1"), 2025)
    created = await _assign(client, headers, MARTA, sy)
    r = await client.patch(
        f"{URL}/{created['id_professor_section_year']}",
        json={"id_professor": MARTA, "id_section_year": sy},
        headers=headers,
    )
    assert r.status_code == 200


async def test_patch_not_found(client, login):
    r = await client.patch(f"{URL}/999", json={"id_professor": MARTA}, headers=await login(SUPER_ADMIN))
    assert r.status_code == 404


async def test_patch_unknown_references_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    sy = await _section_year(client, headers, await _section(client, headers, "3K1"), 2025)
    created = await _assign(client, headers, MARTA, sy)
    url = f"{URL}/{created['id_professor_section_year']}"
    assert (await client.patch(url, json={"id_professor": 999}, headers=headers)).status_code == 404
    assert (await client.patch(url, json={"id_professor": 1}, headers=headers)).status_code == 404
    assert (await client.patch(url, json={"id_section_year": 999}, headers=headers)).status_code == 404


async def test_patch_invalid_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    sy = await _section_year(client, headers, await _section(client, headers, "3K1"), 2025)
    created = await _assign(client, headers, MARTA, sy)
    url = f"{URL}/{created['id_professor_section_year']}"
    for body in ({}, {"id_professor": 0}, {"id_section_year": 0}, {"id_professor": MARTA, "extra": 1}):
        r = await client.patch(url, json=body, headers=headers)
        assert r.status_code == 422, body


# ---------- eliminar ----------
async def test_delete_assignment(client, login):
    headers = await login(SUPER_ADMIN)
    sy = await _section_year(client, headers, await _section(client, headers, "3K1"), 2025)
    created = await _assign(client, headers, MARTA, sy)
    url = f"{URL}/{created['id_professor_section_year']}"
    assert (await client.delete(url, headers=headers)).status_code == 204
    assert (await client.get(url, headers=headers)).status_code == 404
    assert (await client.get(URL, headers=headers)).json()["total"] == 0
    # solo se quitó la relación: el profesor y el curso lectivo siguen existiendo
    assert (await client.get(f"/section-years/{sy}", headers=headers)).status_code == 200
    assert (await client.get("/users?role=professor", headers=headers)).json()["total"] == 1


async def test_delete_not_found(client, login):
    assert (await client.delete(f"{URL}/999", headers=await login(SUPER_ADMIN))).status_code == 404


async def test_cannot_delete_section_year_in_use(client, login):
    headers = await login(SUPER_ADMIN)
    sy = await _section_year(client, headers, await _section(client, headers, "3K1"), 2025)
    created = await _assign(client, headers, MARTA, sy)
    assert (await client.delete(f"/section-years/{sy}", headers=headers)).status_code == 409
    await client.delete(f"{URL}/{created['id_professor_section_year']}", headers=headers)
    assert (await client.delete(f"/section-years/{sy}", headers=headers)).status_code == 204


async def test_deleted_assignment_can_be_recreated(client, login):
    headers = await login(SUPER_ADMIN)
    sy = await _section_year(client, headers, await _section(client, headers, "3K1"), 2025)
    created = await _assign(client, headers, MARTA, sy)
    await client.delete(f"{URL}/{created['id_professor_section_year']}", headers=headers)
    await _assign(client, headers, MARTA, sy)