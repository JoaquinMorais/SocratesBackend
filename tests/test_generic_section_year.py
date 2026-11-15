from tests.helpers import STUDENT, SUPER_ADMIN


async def _generic(client, headers):
    return await client.get("/section-years/generic", headers=headers)


async def test_generic_section_year_exists_and_is_public(client, login):
    admin = await login(SUPER_ADMIN)
    body = (await _generic(client, admin)).json()
    assert body["section_name"] == "PRESOCRATICO"
    assert body["year"] == 2000
    assert body["is_generic"] is True
    assert (await _generic(client, await login(STUDENT))).status_code == 200


async def test_generic_is_excluded_from_normal_lists(client, login):
    admin = await login(SUPER_ADMIN)
    generic = (await _generic(client, admin)).json()

    section_years = (await client.get("/section-years", headers=admin)).json()
    assert generic["id_section_year"] not in {
        item["id_section_year"] for item in section_years["items"]
    }
    sections = (await client.get("/sections", headers=admin)).json()
    assert generic["id_section"] not in {
        item["id_section"] for item in sections["items"]
    }


async def test_generic_is_read_only_in_admin_endpoints(client, login):
    admin = await login(SUPER_ADMIN)
    generic = (await _generic(client, admin)).json()
    sy_id = generic["id_section_year"]
    section_id = generic["id_section"]

    assert (
        await client.patch(
            f"/section-years/{sy_id}", json={"year": 2001}, headers=admin
        )
    ).status_code == 409
    assert (
        await client.patch(
            f"/section-years/{sy_id}/settings",
            json={"allow_project_joins": True},
            headers=admin,
        )
    ).status_code == 409
    assert (
        await client.delete(f"/section-years/{sy_id}", headers=admin)
    ).status_code == 409
    assert (
        await client.patch(
            f"/sections/{section_id}", json={"name": "OTRO"}, headers=admin
        )
    ).status_code == 409
    assert (
        await client.delete(f"/sections/{section_id}", headers=admin)
    ).status_code == 409


async def test_is_generic_cannot_be_set_from_api(client, login):
    admin = await login(SUPER_ADMIN)
    section = await client.post(
        "/sections", json={"name": "NORMAL", "is_generic": True}, headers=admin
    )
    assert section.status_code == 422
    sy = await client.post(
        "/section-years",
        json={
            "year": 2025,
            "id_section": 1,
            "min_students": 1,
            "max_students": 10,
            "is_generic": True,
        },
        headers=admin,
    )
    assert sy.status_code == 422


async def test_any_professor_can_create_and_edit_example_projects(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    generic = (await _generic(client, admin)).json()
    professor = await login(
        await make_professor("prof-generic-examples@frc.utn.edu.ar")
    )
    r = await client.post(
        "/projects",
        json={"id_section_year": generic["id_section_year"]},
        headers=professor,
    )
    assert r.status_code == 201, r.text
    project = r.json()
    assert project["id_section_year"] == generic["id_section_year"]

    r = await client.patch(
        f"/projects/{project['id_project']}",
        json={"name": "Ejemplo", "description": "Proyecto de ejemplo"},
        headers=professor,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Ejemplo"
    assert r.json()["description"] == "Proyecto de ejemplo"

    listed = (
        await client.get(
            "/projects",
            params={"id_section_year": generic["id_section_year"]},
            headers=await login(STUDENT),
        )
    ).json()
    assert project["id_project"] in {
        item["id_project"] for item in listed["items"]
    }


async def test_generic_projects_are_excluded_from_technology_statistics(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    generic = (await _generic(client, admin)).json()
    professor = await login(
        await make_professor("prof-generic-tech@frc.utn.edu.ar")
    )
    project = (
        await client.post(
            "/projects",
            json={"id_section_year": generic["id_section_year"]},
            headers=professor,
        )
    ).json()
    technology = (
        await client.post(
            "/technologies", json={"name": "EjemploTech"}, headers=admin
        )
    ).json()
    assert (
        await client.post(
            f"/projects/{project['id_project']}/technologies",
            json={"id_technology": technology["id_technology"]},
            headers=professor,
        )
    ).status_code == 201

    body = (
        await client.get("/project-technologies/statistics", headers=await login(STUDENT))
    ).json()
    assert body["totals"] == {
        "projects_total": 0,
        "projects_with_technologies": 0,
    }
    assert body["years"] == []
    assert body["technologies"] == []
