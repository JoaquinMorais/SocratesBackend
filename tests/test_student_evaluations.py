from sqlmodel import select

from config.database import SessionLocal
from models import StudentProject
from tests.helpers import (
    STUDENT,
    SUPER_ADMIN,
    assign_professor,
    create_cursada,
    section_year,
)
from utils.statuses import get_status

URL = "/student-evaluations"
ANA_ID, LUIS_ID = 1, 2
ANA = "100001@sistemas.frc.utn.edu.ar"
LUIS = "100002@sistemas.frc.utn.edu.ar"


async def _project(client, admin, sy: int) -> dict:
    r = await client.post("/projects", json={"id_section_year": sy}, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()


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


async def _create_evaluation(client, headers, sy: int, name: str = "Parcial 1"):
    return await client.post(
        f"/section-years/{sy}/student-evaluations",
        json={"name": name, "date": "2026-05-10", "description": "Parcial"},
        headers=headers,
    )


async def _setup(client, admin, make_professor, *, assigned=True):
    sy = await section_year(client, admin, "3K1", 2026)
    ana = await create_cursada(ANA_ID, sy)
    luis = await create_cursada(LUIS_ID, sy)
    mail = await make_professor("prof-eval-students@frc.utn.edu.ar")
    if assigned:
        await assign_professor(client, admin, mail, sy)
    return {"sy": sy, "ana": ana, "luis": luis, "mail": mail}


async def _grades(client, headers, id_evaluation: int):
    return await client.get(
        f"{URL}/{id_evaluation}/grades", headers=headers
    )


def _eval_url(id_evaluation: int, suffix: str = "") -> str:
    return f"{URL}/{id_evaluation}{suffix}"


async def test_assigned_professor_can_manage_evaluation(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    headers = await login(ctx["mail"])

    r = await _create_evaluation(client, headers, ctx["sy"], "Parcial profesor")
    assert r.status_code == 201, r.text
    evaluation = r.json()
    eval_url = _eval_url(evaluation["id_student_evaluation"])

    listing = (
        await client.get(
            f"/section-years/{ctx['sy']}/student-evaluations", headers=headers
        )
    ).json()
    assert listing["total"] == 1
    one = await client.get(eval_url, headers=headers)
    assert one.status_code == 200 and one.json()["name"] == "Parcial profesor"

    r = await client.patch(eval_url, json={"description": "Editado"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["description"] == "Editado"
    assert (await client.delete(eval_url, headers=headers)).status_code == 204


async def test_evaluation_update_validation(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    first = (await _create_evaluation(client, admin, ctx["sy"], "Primero")).json()
    second = (await _create_evaluation(client, admin, ctx["sy"], "Segundo")).json()
    second_url = _eval_url(second["id_student_evaluation"])

    assert (
        await client.patch(second_url, json={"name": "primero"}, headers=admin)
    ).status_code == 409
    assert (
        await client.patch(second_url, json={"name": None}, headers=admin)
    ).status_code == 422
    assert (
        await client.patch(second_url, json={"date": None}, headers=admin)
    ).status_code == 422
    assert (
        await client.patch(second_url, json={"otro": 1}, headers=admin)
    ).status_code == 422
    assert (await client.get(_eval_url(first["id_student_evaluation"]), headers=admin)).status_code == 200


async def test_delete_evaluation_cascades_grades_and_blocks_section_year(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    evaluation = (await _create_evaluation(client, admin, ctx["sy"])).json()
    eval_id = evaluation["id_student_evaluation"]
    grades = (await _grades(client, admin, eval_id)).json()["items"]
    assert grades
    assert (
        await client.delete(f"/section-years/{ctx['sy']}", headers=admin)
    ).status_code == 409
    assert (await client.delete(_eval_url(eval_id), headers=admin)).status_code == 204
    assert (await _grades(client, admin, eval_id)).status_code == 404


async def test_create_grade_validation(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    evaluation = (await _create_evaluation(client, admin, ctx["sy"])).json()
    eval_id = evaluation["id_student_evaluation"]
    grades = (await _grades(client, admin, eval_id)).json()["items"]
    by_student = {item["id_student"]: item for item in grades}
    ana_grade = by_student[ANA_ID]["id_student_grade"]

    for body in (
        {"id_student_section_year": ctx["ana"].id_student_section_year, "grade": 11},
        {"id_student_section_year": ctx["ana"].id_student_section_year, "grade": -1},
        {"id_student_section_year": ctx["ana"].id_student_section_year, "otro": 1},
    ):
        assert (
            await client.post(f"{URL}/{eval_id}/grades", json=body, headers=admin)
        ).status_code == 422
    assert (
        await client.patch(
            f"/student-grades/{ana_grade}", json={}, headers=admin
        )
    ).status_code == 422
    assert (
        await client.patch(
            f"/student-grades/{ana_grade}", json={"otro": 1}, headers=admin
        )
    ).status_code == 422
    assert (
        await client.patch("/student-grades/999999", json={"grade": 5}, headers=admin)
    ).status_code == 404

    registered = await client.post(
        "/student-section-years",
        json={"id_student": LUIS_ID, "id_section_year": ctx["sy"]},
        headers=admin,
    )
    assert registered.status_code == 201, registered.text
    assert (
        await client.post(
            f"{URL}/{eval_id}/grades",
            json={
                "id_student_section_year": registered.json()[
                    "id_student_section_year"
                ],
                "grade": 5,
            },
            headers=admin,
        )
    ).status_code == 422

    other_sy = await section_year(client, admin, "3K2", 2027)
    other_cursada = await create_cursada(
        ANA_ID, other_sy, state="abandoned"
    )
    assert (
        await client.post(
            f"{URL}/{eval_id}/grades",
            json={
                "id_student_section_year": other_cursada.id_student_section_year,
                "grade": 5,
            },
            headers=admin,
        )
    ).status_code == 422


async def test_bulk_grade_validation_is_all_or_nothing(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    evaluation = (await _create_evaluation(client, admin, ctx["sy"])).json()
    eval_id = evaluation["id_student_evaluation"]
    url = f"{URL}/{eval_id}/grades/bulk"
    grade = (await _grades(client, admin, eval_id)).json()["items"][0]

    duplicate = {
        "grades": [
            {"id_student_section_year": ctx["ana"].id_student_section_year, "grade": 6},
            {"id_student_section_year": ctx["ana"].id_student_section_year, "grade": 7},
        ]
    }
    assert (await client.patch(url, json=duplicate, headers=admin)).status_code == 422
    out_of_range = {
        "grades": [
            {"id_student_section_year": ctx["ana"].id_student_section_year, "grade": 0},
            {"id_student_section_year": ctx["luis"].id_student_section_year, "grade": 11},
        ]
    }
    assert (await client.patch(url, json=out_of_range, headers=admin)).status_code == 422
    assert (await _grades(client, admin, eval_id)).json()["items"][0]["id_student_grade"] == grade["id_student_grade"]
    assert (await _grades(client, admin, eval_id)).json()["items"][0]["grade"] == 0


async def test_evaluation_permissions(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor, assigned=False)
    other = await login(ctx["mail"])
    assert (await _create_evaluation(client, other, ctx["sy"])).status_code == 403
    assert (
        await client.get(
            f"/section-years/{ctx['sy']}/student-evaluations", headers=other
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/section-years/{ctx['sy']}/student-evaluations",
            json={"name": "Parcial 1", "date": "2026-05-10"},
            headers=await login(STUDENT),
        )
    ).status_code == 403


async def test_create_evaluation_precreates_zero_grades(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    r = await _create_evaluation(client, admin, ctx["sy"])
    assert r.status_code == 201, r.text
    evaluation = r.json()
    assert evaluation["name"] == "Parcial 1"
    assert evaluation["year"] == 2026

    grades = (await _grades(client, admin, evaluation["id_student_evaluation"])).json()
    assert grades["items"]
    assert {item["grade"] for item in grades["items"]} == {0}
    assert {item["id_student"] for item in grades["items"]} == {ANA_ID, LUIS_ID}

    assert (
        await _create_evaluation(client, admin, ctx["sy"], "parcial 1")
    ).status_code == 409
    assert (
        await client.post(
            f"/section-years/{ctx['sy']}/student-evaluations",
            json={"name": "Parcial 2", "date": "2027-01-01"},
            headers=admin,
        )
    ).status_code == 422
    assert (
        await client.post(
            f"/section-years/{ctx['sy']}/student-evaluations",
            json={"name": "Parcial 2", "date": "2026-06-01", "otro": 1},
            headers=admin,
        )
    ).status_code == 422


async def test_update_and_delete_evaluation(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    evaluation = (await _create_evaluation(client, admin, ctx["sy"])).json()
    eval_url = f"{URL}/{evaluation['id_student_evaluation']}"

    r = await client.patch(
        eval_url,
        json={"name": "Parcial corregido", "description": None, "date": "2026-06-10"},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Parcial corregido"
    assert r.json()["description"] is None
    assert (await client.patch(eval_url, json={}, headers=admin)).status_code == 422
    assert (
        await client.patch(eval_url, json={"date": "2027-01-01"}, headers=admin)
    ).status_code == 422

    assert (await client.delete(eval_url, headers=admin)).status_code == 204
    assert (
        await client.get(eval_url, headers=admin)
    ).status_code == 404


async def test_student_grades_crud_and_bulk(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    ctx = await _setup(client, admin, make_professor)
    evaluation = (await _create_evaluation(client, admin, ctx["sy"])).json()
    eval_id = evaluation["id_student_evaluation"]
    grades = (await _grades(client, admin, eval_id)).json()["items"]
    by_student = {item["id_student"]: item for item in grades}

    ana_grade = by_student[ANA_ID]["id_student_grade"]
    luis_grade = by_student[LUIS_ID]["id_student_grade"]
    r = await client.patch(
        f"/student-grades/{ana_grade}", json={"grade": 8}, headers=admin
    )
    assert r.status_code == 200, r.text
    assert r.json()["grade"] == 8
    assert (
        await client.patch(
            f"/student-grades/{ana_grade}", json={"grade": 0}, headers=admin
        )
    ).status_code == 422
    assert (
        await client.patch(
            f"/student-grades/{ana_grade}", json={"grade": 11}, headers=admin
        )
    ).status_code == 422

    bulk = {
        "grades": [
            {"id_student_section_year": ctx["ana"].id_student_section_year, "grade": 7},
            {"id_student_section_year": ctx["luis"].id_student_section_year, "grade": 9},
        ]
    }
    r = await client.patch(
        f"{URL}/{eval_id}/grades/bulk", json=bulk, headers=admin
    )
    assert r.status_code == 200, r.text
    assert [item["grade"] for item in r.json()["items"]] == [7, 9]

    bad = {
        "grades": [
            {"id_student_section_year": ctx["ana"].id_student_section_year, "grade": 6},
            {"id_student_section_year": 999999, "grade": 5},
        ]
    }
    assert (
        await client.patch(
            f"{URL}/{eval_id}/grades/bulk", json=bad, headers=admin
        )
    ).status_code == 422
    grades_after = (await _grades(client, admin, eval_id)).json()["items"]
    assert {item["grade"] for item in grades_after} == {7, 9}

    assert (
        await client.delete(f"/student-grades/{luis_grade}", headers=admin)
    ).status_code == 204
    assert (
        await client.post(
            f"{URL}/{eval_id}/grades",
            json={
                "id_student_section_year": ctx["luis"].id_student_section_year,
                "grade": 0,
            },
            headers=admin,
        )
    ).status_code == 201
    assert (
        await client.post(
            f"{URL}/{eval_id}/grades",
            json={
                "id_student_section_year": ctx["luis"].id_student_section_year,
                "grade": 4,
            },
            headers=admin,
        )
    ).status_code == 409


async def test_student_sees_only_own_grades_and_backfill(
    client, login, make_professor
):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2026)
    project = await _project(client, admin, sy)
    await _membership(project["id_project"], ANA_ID)
    ana = await create_cursada(ANA_ID, sy)
    evaluation = (await _create_evaluation(client, admin, sy)).json()
    second = (await _create_evaluation(client, admin, sy, "Parcial 2")).json()

    luis = await login(LUIS)
    r = await client.post(
        f"/projects/{project['id_project']}/members", headers=luis
    )
    assert r.status_code == 201, r.text
    grades = (await _grades(client, admin, evaluation["id_student_evaluation"])).json()
    assert len(grades["items"]) == 2
    second_grades = (
        await _grades(client, admin, second["id_student_evaluation"])
    ).json()
    assert len(second_grades["items"]) == 2

    ana_headers = await login(ANA)
    own = (await client.get("/me/student-evaluations", headers=ana_headers)).json()
    assert len(own["items"]) == 2
    assert {item["id_student_evaluation"] for item in own["items"]} == {
        evaluation["id_student_evaluation"],
        second["id_student_evaluation"],
    }
    assert {item["grade"] for item in own["items"]} == {0}

    assert (
        await client.get("/me/student-evaluations", headers=admin)
    ).status_code == 403
    assert (
        await client.get(
            f"{URL}/{evaluation['id_student_evaluation']}", headers=ana_headers
        )
    ).status_code == 403


async def test_statistics_include_student_evaluation_grades(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2026)
    project = await _project(client, admin, sy)
    await _membership(project["id_project"], ANA_ID)
    await create_cursada(ANA_ID, sy)
    evaluation = (await _create_evaluation(client, admin, sy)).json()
    await _create_evaluation(client, admin, sy, "Parcial 2")
    grade = (
        await _grades(client, admin, evaluation["id_student_evaluation"])
    ).json()["items"][0]
    await client.patch(
        f"/student-grades/{grade['id_student_grade']}", json={"grade": 9}, headers=admin
    )

    body = (await client.get(f"/projects/{project['id_project']}/evaluations", headers=admin)).json()
    assert len(body["members"][0]["student_evaluations"]) == 2
    assert {item["grade"] for item in body["members"][0]["student_evaluations"]} == {9, 0}
    assert body["members"][0]["average_student_evaluation"] == 9.0
    assert body["statistics"]["student_evaluations"] == {
        "evaluations_total": 2,
        "graded_grades_total": 1,
        "average_grade": 9.0,
    }

    stats_body = (
        await client.get(f"/projects/{project['id_project']}/statistics", headers=admin)
    ).json()
    assert stats_body["statistics"]["student_evaluations"]["average_grade"] == 9.0
    assert stats_body["member_statistics"][0]["average_student_evaluation"] == 9.0

    student_stats = (
        await client.get("/students/statistics/attending", headers=admin)
    ).json()
    ana_item = next(
        item for item in student_stats["items"] if item["id_student"] == ANA_ID
    )
    assert {
        item["grade"] for item in ana_item["section_years"][0]["student_evaluations"]
    } == {9, 0}
    assert ana_item["section_years"][0]["average_student_evaluation"] == 9.0

    section_body = (
        await client.get(f"/section-years/{sy}/evaluations", headers=admin)
    ).json()
    section_project = next(
        item for item in section_body["projects"]
        if item["project"]["id_project"] == project["id_project"]
    )
    assert section_project["members"][0]["average_student_evaluation"] == 9.0
