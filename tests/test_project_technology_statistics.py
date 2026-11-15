from tests.helpers import STUDENT, SUPER_ADMIN, section_year

URL = "/project-technologies/statistics"
ANA = "100001@sistemas.frc.utn.edu.ar"


async def _project(client, admin, id_section_year: int, **fields) -> dict:
    r = await client.post(
        "/projects", json={"id_section_year": id_section_year}, headers=admin
    )
    assert r.status_code == 201, r.text
    project = r.json()
    if fields:
        r = await client.patch(
            f"/projects/{project['id_project']}", json=fields, headers=admin
        )
        assert r.status_code == 200, r.text
        project = r.json()
    return project


async def _technology(client, admin, name: str) -> dict:
    r = await client.post("/technologies", json={"name": name}, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()


async def _link(client, admin, id_project: int, id_technology: int) -> None:
    r = await client.post(
        f"/projects/{id_project}/technologies",
        json={"id_technology": id_technology},
        headers=admin,
    )
    assert r.status_code == 201, r.text


async def _statistics(client, headers):
    return await client.get(URL, headers=headers)


async def test_requires_authentication(client):
    assert (await client.get(URL)).status_code == 401


async def test_any_user_can_read_aggregated_data(client, login):
    admin = await login(SUPER_ADMIN)
    sy_2024 = await section_year(client, admin, "3K1", 2024)
    sy_2025 = await section_year(client, admin, "3K2", 2025)
    public = await _project(client, admin, sy_2024, privacy="public")
    private = await _project(client, admin, sy_2024, privacy="private")
    protected = await _project(client, admin, sy_2024, privacy="protected")
    next_public = await _project(client, admin, sy_2025, privacy="public")
    next_private = await _project(client, admin, sy_2025, privacy="private")
    await _project(client, admin, sy_2025)

    react = await _technology(client, admin, "React")
    fastapi = await _technology(client, admin, "FastAPI")
    await _technology(client, admin, "Django")  # sin uso: no aparece
    await _link(client, admin, public["id_project"], react["id_technology"])
    await _link(client, admin, public["id_project"], fastapi["id_technology"])
    await _link(client, admin, private["id_project"], react["id_technology"])
    await _link(client, admin, next_public["id_project"], react["id_technology"])
    await _link(client, admin, next_public["id_project"], fastapi["id_technology"])
    await _link(client, admin, next_private["id_project"], fastapi["id_technology"])

    body = (await _statistics(client, await login(STUDENT))).json()
    assert body["totals"] == {
        "projects_total": 6,
        "projects_with_technologies": 4,
    }
    assert [year["year"] for year in body["years"]] == [2024, 2025]

    year_2024 = body["years"][0]
    assert year_2024["projects_total"] == 3
    assert year_2024["projects_with_technologies"] == 2
    assert [item["name"] for item in year_2024["technologies"]] == [
        "React",
        "FastAPI",
    ]
    assert year_2024["technologies"][0]["projects_count"] == 2
    assert year_2024["technologies"][0]["projects_percentage"] == 100.0
    assert year_2024["technologies"][1]["projects_count"] == 1
    assert year_2024["technologies"][1]["projects_percentage"] == 50.0
    assert year_2024["sections"][0]["section_name"] == "3K1"
    assert year_2024["sections"][0]["projects_total"] == 3
    assert year_2024["sections"][0]["projects_with_technologies"] == 2

    year_2025 = body["years"][1]
    assert year_2025["projects_total"] == 3
    assert year_2025["projects_with_technologies"] == 2
    assert [item["name"] for item in year_2025["technologies"]] == [
        "FastAPI",
        "React",
    ]
    assert year_2025["technologies"][0]["projects_percentage"] == 100.0
    assert year_2025["technologies"][1]["projects_percentage"] == 50.0

    assert [item["name"] for item in body["technologies"]] == [
        "FastAPI",
        "React",
    ]
    assert {item["id_technology"] for item in body["technologies"]} == {
        fastapi["id_technology"],
        react["id_technology"],
    }
    assert body["technologies"][0]["projects_count"] == 3
    assert "id_project" not in body["years"][0]["sections"][0]
    assert "id_project" not in str(body)


async def test_empty_statistics(client, login):
    admin = await login(SUPER_ADMIN)
    await section_year(client, admin, "3K1", 2026)
    body = (await _statistics(client, admin)).json()
    assert body == {
        "totals": {"projects_total": 0, "projects_with_technologies": 0},
        "years": [],
        "technologies": [],
    }
