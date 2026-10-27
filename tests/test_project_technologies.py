from config.database import SessionLocal
from models import Project, StudentProject
from tests.helpers import STUDENT, SUPER_ADMIN
from utils.statuses import get_status

LUIS = "100002@sistemas.frc.utn.edu.ar"
ANA_ID, LUIS_ID = 1, 2


# ---------- helpers ----------
async def _section_year(client, headers, name: str = "3K1", year: int = 2025) -> int:
    r = await client.post("/sections", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    r = await client.post(
        "/section-years",
        json={"year": year, "id_section": r.json()["id_section"], "min_students": 1, "max_students": 10},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id_section_year"]


async def _create_project(client, headers, name: str = "3K1", year: int = 2025) -> dict:
    sy = await _section_year(client, headers, name=name, year=year)
    r = await client.post("/projects", json={"id_section_year": sy}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def _create_technology(client, headers, name: str = "React") -> dict:
    r = await client.post("/technologies", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def _add(client, headers, id_project: int, id_technology: int):
    return await client.post(
        f"/projects/{id_project}/technologies", json={"id_technology": id_technology}, headers=headers
    )


async def _bulk(client, headers, id_project: int, id_technologies: list[int]):
    return await client.post(
        f"/projects/{id_project}/technologies/bulk",
        json={"id_technologies": id_technologies},
        headers=headers,
    )


async def _list(client, headers, id_project: int, **params):
    return await client.get(
        f"/projects/{id_project}/technologies", params=params, headers=headers
    )


async def _remove(client, headers, id_project: int, id_technology: int):
    return await client.delete(
        f"/projects/{id_project}/technologies/{id_technology}", headers=headers
    )


async def _add_membership(id_project: int, id_student: int, is_leader: bool = False) -> None:
    async with SessionLocal() as s:
        status = await get_status(s, "student_project", "active")
        membership = StudentProject(
            id_student=id_student,
            id_project=id_project,
            id_status=status.id_status,
            is_leader=is_leader,
        )
        s.add(membership)
        await s.commit()


async def _set_status(id_project: int, code: str) -> None:
    async with SessionLocal() as s:
        status = await get_status(s, "project", code)
        project = await s.get(Project, id_project)
        project.id_status = status.id_status
        s.add(project)
        await s.commit()


async def _set_privacy(id_project: int, privacy: str) -> None:
    async with SessionLocal() as s:
        project = await s.get(Project, id_project)
        project.privacy = privacy
        s.add(project)
        await s.commit()


async def _prof_id(client, headers, mail: str) -> int:
    r = await client.get("/users", params={"q": mail}, headers=headers)
    return r.json()["items"][0]["id_user"]


async def _assign_professor(client, admin, mail: str, id_section_year: int) -> None:
    r = await client.post(
        "/professor-section-years",
        json={"id_professor": await _prof_id(client, admin, mail), "id_section_year": id_section_year},
        headers=admin,
    )
    assert r.status_code == 201, r.text


# ---------- permisos ----------
async def test_requires_authentication(client):
    endpoints = [
        ("POST", "/projects/1/technologies", {"id_technology": 1}),
        ("POST", "/projects/1/technologies/bulk", {"id_technologies": [1]}),
        ("GET", "/projects/1/technologies", None),
        ("DELETE", "/projects/1/technologies/1", None),
    ]
    for method, url, body in endpoints:
        r = await client.request(method, url, json=body)
        assert r.status_code == 401, (method, url)


async def test_student_without_privileges_cannot_manage(client, login):
    headers = await login(SUPER_ADMIN)
    project = await _create_project(client, headers)
    pid = project["id_project"]
    tech = await _create_technology(client, headers)
    luis = await login(LUIS)
    assert (await _add(client, luis, pid, tech["id_technology"])).status_code == 403
    assert (await _bulk(client, luis, pid, [tech["id_technology"]])).status_code == 403
    assert (await _remove(client, luis, pid, tech["id_technology"])).status_code == 403


async def test_unassigned_professor_cannot_manage(client, login, make_professor):
    headers = await login(SUPER_ADMIN)
    project = await _create_project(client, headers)
    pid = project["id_project"]
    tech = await _create_technology(client, headers)
    prof = await login(await make_professor("prof-ptech@frc.utn.edu.ar"))
    assert (await _add(client, prof, pid, tech["id_technology"])).status_code == 403
    assert (await _bulk(client, prof, pid, [tech["id_technology"]])).status_code == 403
    assert (await _remove(client, prof, pid, tech["id_technology"])).status_code == 403


async def test_member_can_manage(client, login):
    headers = await login(SUPER_ADMIN)
    project = await _create_project(client, headers)
    pid = project["id_project"]
    await _add_membership(pid, ANA_ID, is_leader=True)
    tech = await _create_technology(client, headers)
    ana = await login(STUDENT)
    assert (await _add(client, ana, pid, tech["id_technology"])).status_code == 201
    assert (await _remove(client, ana, pid, tech["id_technology"])).status_code == 204


async def test_assigned_professor_can_manage(client, login, make_professor):
    prof_mail = await make_professor("assigned-tech@frc.utn.edu.ar")
    admin = await login(SUPER_ADMIN)
    id_section_year = await _section_year(client, admin)
    await _assign_professor(client, admin, prof_mail, id_section_year)
    r = await client.post("/projects", json={"id_section_year": id_section_year}, headers=admin)
    assert r.status_code == 201, r.text
    pid = r.json()["id_project"]
    tech = await _create_technology(client, admin)
    prof = await login(prof_mail)
    assert (await _add(client, prof, pid, tech["id_technology"])).status_code == 201
    assert (await _remove(client, prof, pid, tech["id_technology"])).status_code == 204


async def test_unknown_project(client, login):
    headers = await login(SUPER_ADMIN)
    assert (await _add(client, headers, 999, 1)).status_code == 404
    assert (await _bulk(client, headers, 999, [1])).status_code == 404
    assert (await _list(client, headers, 999)).status_code == 404
    assert (await _remove(client, headers, 999, 1)).status_code == 404


async def test_any_logged_user_can_list_public_project(client, login):
    headers = await login(SUPER_ADMIN)
    project = await _create_project(client, headers)
    luis = await login(LUIS)
    r = await _list(client, luis, project["id_project"])
    assert r.status_code == 200 and r.json()["total"] == 0, r.text


# ---------- agregar ----------
async def test_add_technology(client, login):
    headers = await login(SUPER_ADMIN)
    project = await _create_project(client, headers)
    pid = project["id_project"]
    tech = await _create_technology(client, headers)
    r = await _add(client, headers, pid, tech["id_technology"])
    assert r.status_code == 201 and r.json() == tech, r.text
    body = (await _list(client, headers, pid)).json()
    assert body["total"] == 1 and body["items"][0]["name"] == tech["name"]


async def test_add_duplicate_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    project = await _create_project(client, headers)
    pid = project["id_project"]
    tech = await _create_technology(client, headers)
    assert (await _add(client, headers, pid, tech["id_technology"])).status_code == 201
    assert (await _add(client, headers, pid, tech["id_technology"])).status_code == 409


async def test_add_unknown_technology(client, login):
    headers = await login(SUPER_ADMIN)
    project = await _create_project(client, headers)
    pid = project["id_project"]
    assert (await _add(client, headers, pid, 999)).status_code == 404


async def test_add_invalid_body_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    project = await _create_project(client, headers)
    pid = project["id_project"]
    for body in ({}, {"id_technology": 0}, {"id_technology": -1}, {"extra": 1},
                 {"id_technology": 1, "extra": 2}):
        r = await client.post(f"/projects/{pid}/technologies", json=body, headers=headers)
        assert r.status_code == 422, body


async def test_add_allowed_while_insured_not_final(client, login):
    headers = await login(SUPER_ADMIN)
    project = await _create_project(client, headers)
    pid = project["id_project"]
    tech = await _create_technology(client, headers)
    await _set_status(pid, "in_idea")
    assert (await _add(client, headers, pid, tech["id_technology"])).status_code == 201


async def test_changes_rejected_on_final_project(client, login):
    headers = await login(SUPER_ADMIN)
    project = await _create_project(client, headers)
    pid = project["id_project"]
    tech = await _create_technology(client, headers)
    await _set_status(pid, "approved")
    assert (await _add(client, headers, pid, tech["id_technology"])).status_code == 409
    assert (await _bulk(client, headers, pid, [tech["id_technology"]])).status_code == 409
    assert (await _remove(client, headers, pid, tech["id_technology"])).status_code == 409


# ---------- alta en lote ----------
async def test_bulk_add(client, login):
    headers = await login(SUPER_ADMIN)
    project = await _create_project(client, headers)
    pid = project["id_project"]
    react = await _create_technology(client, headers, "React")
    angular = await _create_technology(client, headers, "Angular")
    vue = await _create_technology(client, headers, "Vue")
    ids = [react["id_technology"], vue["id_technology"], angular["id_technology"]]
    r = await _bulk(client, headers, pid, ids)
    assert r.status_code == 201, r.text
    assert [t["name"] for t in r.json()] == ["Angular", "React", "Vue"]
    assert (await _list(client, headers, pid)).json()["total"] == 3


async def test_bulk_all_or_nothing(client, login):
    headers = await login(SUPER_ADMIN)
    project = await _create_project(client, headers)
    pid = project["id_project"]
    tech = await _create_technology(client, headers)
    r = await _bulk(client, headers, pid, [tech["id_technology"], 999])
    assert r.status_code == 422, r.text
    errors = r.json()["detail"]
    assert errors == [{"row": 2, "id_technology": 999, "detail": "Technology not found"}]
    assert (await _list(client, headers, pid)).json()["total"] == 0


async def test_bulk_duplicated_in_request(client, login):
    headers = await login(SUPER_ADMIN)
    project = await _create_project(client, headers)
    pid = project["id_project"]
    tid = (await _create_technology(client, headers))["id_technology"]
    r = await _bulk(client, headers, pid, [tid, tid])
    assert r.status_code == 422, r.text
    errors = r.json()["detail"]
    row2 = next(e for e in errors if e["row"] == 2)
    assert row2["id_technology"] == tid
    assert "first seen in row 1" in row2["detail"]
    assert (await _list(client, headers, pid)).json()["total"] == 0


async def test_bulk_already_linked(client, login):
    headers = await login(SUPER_ADMIN)
    project = await _create_project(client, headers)
    pid = project["id_project"]
    linked = await _create_technology(client, headers, "React")
    other = await _create_technology(client, headers, "Vue")
    assert (await _add(client, headers, pid, linked["id_technology"])).status_code == 201
    r = await _bulk(client, headers, pid, [linked["id_technology"], other["id_technology"]])
    assert r.status_code == 422, r.text
    errors = r.json()["detail"]
    assert len(errors) == 1
    assert errors[0]["row"] == 1
    assert errors[0]["id_technology"] == linked["id_technology"]
    assert errors[0]["detail"] == "Technology is already linked to this project"
    assert (await _list(client, headers, pid)).json()["total"] == 1


async def test_bulk_invalid_body_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    project = await _create_project(client, headers)
    pid = project["id_project"]
    for body in ({}, {"id_technologies": []}, {"id_technologies": list(range(101))},
                 {"id_technologies": [1], "extra": 1}):
        r = await client.post(f"/projects/{pid}/technologies/bulk", json=body, headers=headers)
        assert r.status_code == 422, body


# ---------- consultar ----------
async def test_list_q_filter(client, login):
    headers = await login(SUPER_ADMIN)
    project = await _create_project(client, headers)
    pid = project["id_project"]
    react = await _create_technology(client, headers, "React")
    await _create_technology(client, headers, "Redux")
    vue = await _create_technology(client, headers, "Vue")
    await _bulk(client, headers, pid, [react["id_technology"], vue["id_technology"]])
    body = (await _list(client, headers, pid, q="re")).json()
    assert body["total"] == 1 and body["items"][0]["name"] == "React"
    assert (await _list(client, headers, pid, q="xxx")).json()["total"] == 0


async def test_list_pagination(client, login):
    headers = await login(SUPER_ADMIN)
    project = await _create_project(client, headers)
    pid = project["id_project"]
    for name in ("Angular", "React", "Vue"):
        tech = await _create_technology(client, headers, name)
        await _add(client, headers, pid, tech["id_technology"])
    page1 = (await _list(client, headers, pid, limit=2)).json()
    assert len(page1["items"]) == 2 and page1["total"] == 3
    page2 = (await _list(client, headers, pid, limit=2, offset=2)).json()
    assert len(page2["items"]) == 1
    assert (await _list(client, headers, pid, limit=0)).status_code == 422


async def test_list_private_visible_only_to_privileged(client, login):
    headers = await login(SUPER_ADMIN)
    project = await _create_project(client, headers)
    pid = project["id_project"]
    tech = await _create_technology(client, headers)
    await _add(client, headers, pid, tech["id_technology"])
    await _set_status(pid, "in_idea")  # insured: la privacidad almacenada aplica
    await _set_privacy(pid, "private")
    luis = await login(LUIS)
    assert (await _list(client, luis, pid)).status_code == 403
    await _add_membership(pid, ANA_ID, is_leader=True)
    body = (await _list(client, await login(STUDENT), pid)).json()
    assert body["total"] == 1 and body["items"][0]["name"] == tech["name"]


async def test_list_protected_visible_to_any_user(client, login):
    headers = await login(SUPER_ADMIN)
    project = await _create_project(client, headers)
    pid = project["id_project"]
    tech = await _create_technology(client, headers)
    await _add(client, headers, pid, tech["id_technology"])
    await _set_status(pid, "in_idea")
    await _set_privacy(pid, "protected")
    body = (await _list(client, await login(LUIS), pid)).json()
    assert body["total"] == 1 and body["items"][0]["name"] == tech["name"]


# ---------- quitar ----------
async def test_remove_technology(client, login):
    headers = await login(SUPER_ADMIN)
    project = await _create_project(client, headers)
    pid = project["id_project"]
    react = await _create_technology(client, headers, "React")
    vue = await _create_technology(client, headers, "Vue")
    await _add(client, headers, pid, react["id_technology"])
    await _add(client, headers, pid, vue["id_technology"])
    assert (await _remove(client, headers, pid, react["id_technology"])).status_code == 204
    body = (await _list(client, headers, pid)).json()
    assert body["total"] == 1 and body["items"][0]["name"] == "Vue"
    # la tecnología sigue existiendo globalmente
    r = await client.get(f"/technologies/{react['id_technology']}", headers=headers)
    assert r.status_code == 200


async def test_remove_not_linked(client, login):
    headers = await login(SUPER_ADMIN)
    project = await _create_project(client, headers)
    pid = project["id_project"]
    tech = await _create_technology(client, headers)
    assert (await _remove(client, headers, pid, tech["id_technology"])).status_code == 404


# ---------- borrar el proyecto ----------
async def test_delete_project_cascades_links(client, login):
    headers = await login(SUPER_ADMIN)
    project = await _create_project(client, headers)
    pid = project["id_project"]
    tech = await _create_technology(client, headers)
    await _add(client, headers, pid, tech["id_technology"])
    assert (await client.delete(f"/projects/{pid}", headers=headers)).status_code == 204
    assert (await _list(client, headers, pid)).status_code == 404
    # la tecnología sobrevive al proyecto
    assert (await client.get(f"/technologies/{tech['id_technology']}", headers=headers)).status_code == 200
    # un proyecto nuevo del mismo curso lectivo de la misma comisión arranca sin vínculos
    sy = await _section_year(client, headers, name="3K2")
    r = await client.post("/projects", json={"id_section_year": sy}, headers=headers)
    assert (await _list(client, headers, r.json()["id_project"])).json()["total"] == 0
