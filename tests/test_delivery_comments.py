from sqlmodel import select

from config.database import SessionLocal
from models import ProfessorSectionYear, StudentProject
from tests.helpers import SUPER_ADMIN, assign_professor, section_year
from utils.statuses import get_status

PROJECTS = "/projects"
ANA_ID = 1
LUIS_ID = 2
ANA = "100001@sistemas.frc.utn.edu.ar"
LUIS = "100002@sistemas.frc.utn.edu.ar"


async def _membership(id_project: int, id_student: int, code: str = "active"):
    async with SessionLocal() as session:
        membership_status = await get_status(session, "student_project", code)
        session.add(
            StudentProject(
                id_project=id_project,
                id_student=id_student,
                id_status=membership_status.id_status,
            )
        )
        await session.commit()


async def _setup(client, admin, make_professor, *, assigned: bool = True):
    sy = await section_year(client, admin, "3K1", 2026)
    project = (
        await client.post(PROJECTS, json={"id_section_year": sy}, headers=admin)
    ).json()
    r = await client.post(
        f"/section-years/{sy}/activities",
        json={"title": "Entrega", "due_date": "2026-05-15"},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    activity = r.json()
    deliveries = (
        await client.get(
            f"{PROJECTS}/{project['id_project']}/deliveries", headers=admin
        )
    ).json()
    delivery = deliveries["items"][0]
    await _membership(project["id_project"], ANA_ID)
    professor_mail = await make_professor("prof-comments@frc.utn.edu.ar")
    if assigned:
        await assign_professor(client, admin, professor_mail, sy)
    return {
        "sy": sy,
        "project": project,
        "activity": activity,
        "delivery": delivery,
        "professor_mail": professor_mail,
    }


async def _project(client, admin, id_section_year: int) -> dict:
    r = await client.post(PROJECTS, json={"id_section_year": id_section_year}, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()


async def _activity(client, admin, id_section_year: int, title: str) -> dict:
    r = await client.post(
        f"/section-years/{id_section_year}/activities",
        json={"title": title, "due_date": "2026-05-15"},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _delivery_id(client, admin, id_project: int, id_activity: int) -> int:
    body = (
        await client.get(f"{PROJECTS}/{id_project}/deliveries", headers=admin)
    ).json()
    return next(
        item["id_delivery"]
        for item in body["items"]
        if item["id_activity"] == id_activity
    )


async def _create(client, headers, id_delivery: int, content: str, kind: str | None = None):
    body = {"content": content}
    if kind is not None:
        body["kind"] = kind
    return await client.post(
        f"/deliveries/{id_delivery}/comments", json=body, headers=headers
    )


async def _list(client, headers, id_delivery: int, **params):
    return await client.get(
        f"/deliveries/{id_delivery}/comments", params=params, headers=headers
    )


# ---------- permisos ----------
async def test_requires_authentication(client):
    assert (await client.get("/deliveries/1/comments")).status_code == 401
    assert (
        await client.post(
            "/deliveries/1/comments", json={"content": "Hola"}
        )
    ).status_code == 401
    assert (await client.get("/delivery-comments/1")).status_code == 401
    assert (
        await client.patch(
            "/delivery-comments/1", json={"content": "Hola"}
        )
    ).status_code == 401
    assert (
        await client.post("/delivery-comments/1/correct")
    ).status_code == 401


async def test_student_and_unassigned_professor_cannot_create(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor, assigned=False)
    assert (
        await _create(client, await login(ANA), ctx["delivery"]["id_delivery"], "Hola")
    ).status_code == 403
    assert (
        await _create(
            client,
            await login(ctx["professor_mail"]),
            ctx["delivery"]["id_delivery"],
            "Hola",
        )
    ).status_code == 403


async def test_assigned_professor_and_super_admin_can_create(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    delivery_id = ctx["delivery"]["id_delivery"]

    r = await _create(
        client, await login(ctx["professor_mail"]), delivery_id, "  Mejorar el informe  "
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "feedback"
    assert body["content"] == "Mejorar el informe"
    assert body["status"]["code"] == "requested"
    assert body["status"]["ambito"] == "delivery_comment"
    assert body["author"]["first_name"] == "Test"
    assert "email" not in body["author"]

    r = await _create(client, admin, delivery_id, "Nota interna", "annotation")
    assert r.status_code == 201, r.text
    assert r.json()["status"]["code"] == "annotation"


# ---------- consultar ----------
async def test_student_only_sees_feedback(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    delivery_id = ctx["delivery"]["id_delivery"]
    feedback = (await _create(client, admin, delivery_id, "Feedback")).json()
    annotation = (
        await _create(client, admin, delivery_id, "Nota interna", "annotation")
    ).json()

    ana = await login(ANA)
    body = (await _list(client, ana, delivery_id)).json()
    assert body["total"] == 1
    assert [item["id_delivery_comment"] for item in body["items"]] == [
        feedback["id_delivery_comment"]
    ]
    assert (await _list(client, ana, delivery_id, kind="annotation")).status_code == 403
    assert (await client.get("/delivery-comments", headers=ana)).status_code == 403
    assert (
        await client.get(
            f"/projects/{ctx['project']['id_project']}/annotations", headers=ana
        )
    ).status_code == 403
    assert (
        await client.get(
            f"/delivery-comments/{annotation['id_delivery_comment']}", headers=ana
        )
    ).status_code == 403
    assert (
        await client.get(
            f"/delivery-comments/{feedback['id_delivery_comment']}", headers=ana
        )
    ).status_code == 200

    staff = (await _list(client, admin, delivery_id)).json()
    assert staff["total"] == 2
    assert {item["kind"] for item in staff["items"]} == {"feedback", "annotation"}


async def test_list_order_filters_and_pagination(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    delivery_id = ctx["delivery"]["id_delivery"]
    first = (await _create(client, admin, delivery_id, "Uno")).json()
    second = (await _create(client, admin, delivery_id, "Dos")).json()
    third = (await _create(client, admin, delivery_id, "Tres", "annotation")).json()

    body = (await _list(client, admin, delivery_id)).json()
    assert [item["id_delivery_comment"] for item in body["items"]] == [
        third["id_delivery_comment"],
        second["id_delivery_comment"],
        first["id_delivery_comment"],
    ]
    page = (await _list(client, admin, delivery_id, limit=1, offset=1)).json()
    assert page["total"] == 3
    assert [item["id_delivery_comment"] for item in page["items"]] == [
        second["id_delivery_comment"]
    ]
    only_feedback = (await _list(client, admin, delivery_id, kind="feedback")).json()
    assert only_feedback["total"] == 2
    assert (await _list(client, admin, delivery_id, limit=0)).status_code == 422


async def test_annotations_by_project_and_activity(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    second_project = await _project(client, admin, ctx["sy"])
    second_activity = await _activity(client, admin, ctx["sy"], "Otra actividad")
    first_delivery = ctx["delivery"]["id_delivery"]
    second_delivery = await _delivery_id(
        client, admin, ctx["project"]["id_project"], second_activity["id_activity"]
    )
    other_delivery = await _delivery_id(
        client, admin, second_project["id_project"], ctx["activity"]["id_activity"]
    )
    other_second_delivery = await _delivery_id(
        client,
        admin,
        second_project["id_project"],
        second_activity["id_activity"],
    )
    first = (await _create(client, admin, first_delivery, "Alpha", "annotation")).json()
    second = (await _create(client, admin, second_delivery, "Beta", "annotation")).json()
    third = (await _create(client, admin, other_delivery, "Gamma", "annotation")).json()
    await _create(client, admin, other_second_delivery, "Feedback")

    project_list = (
        await client.get(
            f"/projects/{ctx['project']['id_project']}/annotations",
            headers=admin,
        )
    ).json()
    assert project_list["total"] == 2
    assert {item["id_delivery_comment"] for item in project_list["items"]} == {
        first["id_delivery_comment"],
        second["id_delivery_comment"],
    }
    assert {item["id_project"] for item in project_list["items"]} == {
        ctx["project"]["id_project"]
    }
    assert {item["id_activity"] for item in project_list["items"]} == {
        ctx["activity"]["id_activity"],
        second_activity["id_activity"],
    }
    assert all(item["kind"] == "annotation" for item in project_list["items"])
    assert all(item["project"]["id_project"] == ctx["project"]["id_project"] for item in project_list["items"])

    activity_list = (
        await client.get(
            f"/activities/{ctx['activity']['id_activity']}/annotations",
            headers=admin,
        )
    ).json()
    assert activity_list["total"] == 2
    assert {item["id_project"] for item in activity_list["items"]} == {
        ctx["project"]["id_project"],
        second_project["id_project"],
    }

    global_list = (
        await client.get(
            "/delivery-comments",
            params={"kind": "annotation", "id_project": ctx["project"]["id_project"]},
            headers=admin,
        )
    ).json()
    assert global_list["total"] == 2
    assert {item["id_activity"] for item in global_list["items"]} == {
        ctx["activity"]["id_activity"],
        second_activity["id_activity"],
    }

    search = (
        await client.get(
            "/delivery-comments",
            params={"kind": "annotation", "q": "BETA"},
            headers=admin,
        )
    ).json()
    assert search["total"] == 1
    assert search["items"][0]["id_delivery_comment"] == second["id_delivery_comment"]

    all_comments = (await client.get("/delivery-comments", headers=admin)).json()
    assert all_comments["total"] == 4
    page = (
        await client.get(
            "/delivery-comments", params={"limit": 1, "offset": 1}, headers=admin
        )
    ).json()
    assert page["total"] == 4 and len(page["items"]) == 1
    assert (
        await client.get(
            "/delivery-comments", params={"q": "  "}, headers=admin
        )
    ).status_code == 422
    assert (
        await client.get("/delivery-comments", params={"limit": 0}, headers=admin)
    ).status_code == 422


async def test_annotation_list_scope(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    await _create(client, admin, ctx["delivery"]["id_delivery"], "Interna", "annotation")
    unassigned = await login(
        await make_professor("prof-no-comments@frc.utn.edu.ar")
    )

    assert (
        await client.get(
            f"/projects/{ctx['project']['id_project']}/annotations",
            headers=unassigned,
        )
    ).status_code == 403
    assert (
        await client.get(
            f"/activities/{ctx['activity']['id_activity']}/annotations",
            headers=unassigned,
        )
    ).status_code == 403
    assert (
        await client.get(
            "/delivery-comments",
            params={"kind": "annotation", "id_delivery": ctx["delivery"]["id_delivery"]},
            headers=unassigned,
        )
    ).status_code == 403
    assert (await client.get("/delivery-comments", headers=unassigned)).json()["total"] == 0
    assert (
        await client.get(
            "/projects/999999/annotations", headers=admin
        )
    ).status_code == 404
    assert (
        await client.get(
            "/activities/999999/annotations", headers=admin
        )
    ).status_code == 404


# ---------- crear / validaciones ----------
async def test_create_validation(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    delivery_id = ctx["delivery"]["id_delivery"]
    headers = await login(ctx["professor_mail"])

    for body in (
        {},
        {"content": ""},
        {"content": "   "},
        {"content": "x" * 2001},
        {"content": "Hola", "otro": 1},
        {"content": "Hola", "kind": "otro"},
    ):
        r = await client.post(
            f"/deliveries/{delivery_id}/comments", json=body, headers=headers
        )
        assert r.status_code == 422, body
    assert (
        await _create(client, headers, 999999, "Hola")
    ).status_code == 404


# ---------- editar ----------
async def test_author_edits_requested_feedback_only(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    delivery_id = ctx["delivery"]["id_delivery"]
    author = await login(ctx["professor_mail"])
    created = (await _create(client, author, delivery_id, "Original")).json()
    url = f"/delivery-comments/{created['id_delivery_comment']}"

    r = await client.patch(url, json={"content": "  Corregido  "}, headers=author)
    assert r.status_code == 200, r.text
    assert r.json()["content"] == "Corregido"
    assert r.json()["status"]["code"] == "requested"

    other_mail = await make_professor("prof-comments-other@frc.utn.edu.ar")
    await assign_professor(client, admin, other_mail, ctx["sy"])
    other = await login(other_mail)
    assert (await client.patch(url, json={"content": "Otra"}, headers=other)).status_code == 403
    assert (await client.patch(url, json={"content": "Otra"}, headers=admin)).status_code == 403
    assert (await client.patch(url, json={"content": "Otra"}, headers=await login(ANA))).status_code == 403

    assert (await client.patch(url, json={}, headers=author)).status_code == 422
    assert (await client.patch(url, json={"otro": 1}, headers=author)).status_code == 422

    assert (
        await client.post(f"{url}/correct", headers=author)
    ).status_code == 200
    assert (await client.patch(url, json={"content": "Tarde"}, headers=author)).status_code == 409
    assert (await client.patch("/delivery-comments/999", json={"content": "x"}, headers=author)).status_code == 404


async def test_annotation_editable_by_author(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    author = await login(ctx["professor_mail"])
    created = (
        await _create(
            client, author, ctx["delivery"]["id_delivery"], "Interna", "annotation"
        )
    ).json()
    url = f"/delivery-comments/{created['id_delivery_comment']}"

    r = await client.patch(url, json={"content": "Interna editada"}, headers=author)
    assert r.status_code == 200, r.text
    assert r.json()["content"] == "Interna editada"
    assert r.json()["status"]["code"] == "annotation"

    r = await client.patch(url, json={"content": "Editada por staff"}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["content"] == "Editada por staff"
    assert r.json()["status"]["code"] == "annotation"
    assert (await client.post(f"{url}/correct", headers=admin)).status_code == 409

    assigned_mail = await make_professor("prof-annotation-assigned@frc.utn.edu.ar")
    await assign_professor(client, admin, assigned_mail, ctx["sy"])
    r = await client.patch(
        url,
        json={"content": "Editada por otro profesor del curso"},
        headers=await login(assigned_mail),
    )
    assert r.status_code == 200, r.text
    assert r.json()["content"] == "Editada por otro profesor del curso"

    other_mail = await make_professor("prof-annotation-other@frc.utn.edu.ar")
    assert (
        await client.patch(
            url, json={"content": "Otra"}, headers=await login(other_mail)
        )
    ).status_code == 403


# ---------- corregir ----------
async def test_correct_feedback_permissions(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    delivery_id = ctx["delivery"]["id_delivery"]
    feedback = (await _create(client, admin, delivery_id, "Revisar")).json()
    annotation = (
        await _create(client, admin, delivery_id, "Nota", "annotation")
    ).json()
    url = f"/delivery-comments/{feedback['id_delivery_comment']}/correct"

    r = await client.post(url, headers=await login(ANA))
    assert r.status_code == 200, r.text
    assert r.json()["status"]["code"] == "corrected"
    assert r.json()["corrected_at"] is not None
    assert (await client.post(url, headers=admin)).status_code == 409
    assert (
        await client.post(
            f"/delivery-comments/{annotation['id_delivery_comment']}/correct",
            headers=admin,
        )
    ).status_code == 409

    outsider = await login(LUIS)
    second = (await _create(client, admin, delivery_id, "Otra")).json()
    assert (
        await client.post(
            f"/delivery-comments/{second['id_delivery_comment']}/correct",
            headers=outsider,
        )
    ).status_code == 403
    assert (await client.post("/delivery-comments/999/correct", headers=admin)).status_code == 404


async def test_finished_member_and_staff_can_read_and_correct(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    await _membership(ctx["project"]["id_project"], LUIS_ID, "finished")
    delivery_id = ctx["delivery"]["id_delivery"]
    by_student = (await _create(client, admin, delivery_id, "Para Luis")).json()
    by_professor = (
        await _create(
            client,
            await login(ctx["professor_mail"]),
            delivery_id,
            "Para el grupo",
        )
    ).json()

    luis = await login(LUIS)
    body = (await _list(client, luis, delivery_id)).json()
    assert body["total"] == 2
    r = await client.post(
        f"/delivery-comments/{by_student['id_delivery_comment']}/correct",
        headers=luis,
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        f"/delivery-comments/{by_professor['id_delivery_comment']}/correct",
        headers=await login(ctx["professor_mail"]),
    )
    assert r.status_code == 200, r.text


# ---------- efectos ----------
async def test_comments_block_resource_deletion(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    await _create(client, admin, ctx["delivery"]["id_delivery"], "Comentario")

    assert (
        await client.delete(
            f"/activities/{ctx['activity']['id_activity']}", headers=admin
        )
    ).status_code == 409
    assert (
        await client.delete(
            f"{PROJECTS}/{ctx['project']['id_project']}", headers=admin
        )
    ).status_code == 409
    assert (
        await client.delete(f"/section-years/{ctx['sy']}", headers=admin)
    ).status_code == 409


async def test_professor_with_comments_cannot_be_deleted(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    await _create(
        client, await login(ctx["professor_mail"]), ctx["delivery"]["id_delivery"], "Comentario"
    )
    async with SessionLocal() as session:
        assignment = (
            await session.exec(
                select(ProfessorSectionYear).where(
                    ProfessorSectionYear.id_section_year == ctx["sy"]
                )
            )
        ).one()
        await session.delete(assignment)
        await session.commit()
        professor_id = assignment.id_professor

    assert (await client.delete(f"/professors/{professor_id}", headers=admin)).status_code == 409
