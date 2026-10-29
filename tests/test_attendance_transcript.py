from datetime import date

from tests.helpers import STUDENT, SUPER_ADMIN, assign_professor, section_year

URL = "/calendar-classes"
ANA_ID, LUIS_ID = 1, 2


def _class_body(**overrides) -> dict:
    return {
        "date": "2026-03-03",
        "start_time": "18:30",
        "end_time": "22:00",
        "modality": "virtual",
        **overrides,
    }


def _student(legajo: int, first_name: str, last_name: str) -> dict:
    return {
        "first_name": first_name,
        "last_name": last_name,
        "legajo": legajo,
        "birth_date": "2003-05-10",
        "enrollment_year": 2023,
    }


async def _sy(client, headers, name: str = "3K1", year: int = 2026) -> int:
    return await section_year(client, headers, name, year)


async def _class(client, headers, id_section_year: int, **overrides) -> dict:
    r = await client.post(
        f"/section-years/{id_section_year}/calendar-classes",
        json=_class_body(**overrides),
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _enroll(client, headers, id_student: int, id_section_year: int) -> dict:
    r = await client.post(
        "/student-section-years",
        json={"id_student": id_student, "id_section_year": id_section_year},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _new_student(client, headers, legajo: int, first: str, last: str) -> dict:
    r = await client.post(
        "/students", json=_student(legajo, first, last), headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _import_file(
    client,
    headers,
    id_calendar_class: int,
    content: str | bytes,
    *,
    filename: str = "chat.txt",
    **params,
):
    data = content.encode("utf-8") if isinstance(content, str) else content
    return await client.post(
        f"{URL}/{id_calendar_class}/attendance/import-transcript",
        files={"file": (filename, data, "text/plain")},
        params=params,
        headers=headers,
    )


async def _import_text(
    client, headers, id_calendar_class: int, text: str, *, fmt: str = "text", **params
):
    return await client.post(
        f"{URL}/{id_calendar_class}/attendance/import-transcript/text",
        json={"text": text, "format": fmt},
        params=params,
        headers=headers,
    )


def _statuses(report: dict) -> dict[int, str]:
    return {
        item["legajo"]: item["status"]
        for item in report["items"]
        if item["legajo"] is not None
    }


# ---------- permisos ----------
async def test_requires_authentication(client):
    assert (
        await client.post(f"{URL}/1/attendance/import-transcript")
    ).status_code == 401
    assert (
        await client.post(
            f"{URL}/1/attendance/import-transcript/text", json={"text": "100001-A"}
        )
    ).status_code == 401


async def test_permissions(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    await _enroll(client, admin, ANA_ID, sy)
    transcript = "100001-GomezAna"

    student = await login(STUDENT)
    assert (
        await _import_file(client, student, calendar_class["id_calendar_class"], transcript)
    ).status_code == 403

    other = await make_professor("prof-trans-otro@frc.utn.edu.ar")
    assert (
        await _import_file(client, await login(other), calendar_class["id_calendar_class"], transcript)
    ).status_code == 403

    assigned = await make_professor("prof-trans@frc.utn.edu.ar", legajo=300002)
    await assign_professor(client, admin, assigned, sy)
    r = await _import_file(
        client, await login(assigned), calendar_class["id_calendar_class"], transcript
    )
    assert r.status_code == 200, r.text

    # profesor asignado a otro curso lectivo no puede importar en este
    other_sy = await _sy(client, admin, "3K2", 2026)
    await assign_professor(client, admin, other, other_sy)
    r = await _import_file(
        client, await login(other), calendar_class["id_calendar_class"], transcript
    )
    assert r.status_code == 403

    assert (
        await _import_file(client, admin, 999, transcript)
    ).status_code == 404


# ---------- preview y confirmación ----------
async def test_preview_then_confirm(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    await _enroll(client, admin, ANA_ID, sy)
    transcript = "18:30:15 Ana: 100001-GomezAna\n18:31:00 Profe: recuerden la entrega"

    preview = await _import_file(
        client, admin, calendar_class["id_calendar_class"], transcript
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["dry_run"] is True
    assert body["summary"]["would_create"] == 1
    assert body["summary"]["created"] == 0
    assert body["summary"]["ignored_lines"] == 1
    assert _statuses(body)[100001] == "would_create"

    listed = (
        await client.get(
            f"{URL}/{calendar_class['id_calendar_class']}/attendance", headers=admin
        )
    ).json()
    assert listed["items"][0]["present"] is False  # el preview no escribió

    confirmed = await _import_file(
        client,
        admin,
        calendar_class["id_calendar_class"],
        transcript,
        dry_run="false",
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["dry_run"] is False
    assert body["summary"]["created"] == 1
    assert _statuses(body)[100001] == "created"

    listed = (
        await client.get(
            f"{URL}/{calendar_class['id_calendar_class']}/attendance", headers=admin
        )
    ).json()
    assert listed["items"][0]["present"] is True
    assert listed["items"][0]["method"] == "transcript"

    history = (await client.get("/me/attendance", headers=await login(STUDENT))).json()
    assert history["items"][0]["method"] == "transcript"

    again = await _import_file(
        client,
        admin,
        calendar_class["id_calendar_class"],
        transcript,
        dry_run="false",
    )
    assert again.json()["summary"]["already_present"] == 1


async def test_existing_attendance_is_not_overwritten(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    await _enroll(client, admin, ANA_ID, sy)
    opened = (
        await client.post(
            f"{URL}/{calendar_class['id_calendar_class']}/attendance/open",
            headers=admin,
        )
    ).json()
    r = await client.post(
        f"{URL}/{calendar_class['id_calendar_class']}/attendance/check-in",
        json={"code": opened["code"]},
        headers=await login(STUDENT),
    )
    assert r.status_code == 200

    report = (
        await _import_file(
            client,
            admin,
            calendar_class["id_calendar_class"],
            "100001-GomezAna",
            dry_run="false",
        )
    ).json()
    assert report["summary"]["already_present"] == 1
    item = report["items"][0]
    assert item["status"] == "already_present"
    assert item["existing_method"] == "code"

    listed = (
        await client.get(
            f"{URL}/{calendar_class['id_calendar_class']}/attendance", headers=admin
        )
    ).json()
    assert listed["items"][0]["method"] == "code"  # no se pisó


# ---------- matching del nombre ----------
async def test_name_tolerance(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    juan = await _new_student(client, admin, 100010, "Juan Carlos", "Domínguez")
    await _enroll(client, admin, ANA_ID, sy)
    await _enroll(client, admin, LUIS_ID, sy)
    await _enroll(client, admin, juan["id_student"], sy)

    transcript = "\n".join(
        [
            "100001-Gómez Ana",  # tildes y espacio
            "100010-DominguezJuan",  # sin el segundo nombre
            "100010-DominguezCarlos",  # solo el segundo nombre
            "100002-PerezLui",  # typo (falta una letra)
            "100001-AnaGomez",  # orden invertido + duplicado de Ana
        ]
    )
    report = (
        await _import_file(client, admin, calendar_class["id_calendar_class"], transcript)
    ).json()
    statuses = _statuses(report)
    assert statuses[100001] == "would_create"
    assert statuses[100010] == "would_create"
    assert statuses[100002] == "would_create"
    ana = next(item for item in report["items"] if item["legajo"] == 100001)
    assert ana["occurrences"] == 2
    assert ana["name_score"] >= 0.75


async def test_name_mismatch_is_not_marked(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    await _enroll(client, admin, ANA_ID, sy)

    transcript = "\n".join(
        [
            "100001-Gomez",  # solo apellido
            "100001-Ana",  # solo nombre
            "100001-PerezLuis",  # legajo de Ana con nombre de otro
        ]
    )
    report = (
        await _import_file(
            client,
            admin,
            calendar_class["id_calendar_class"],
            transcript,
            dry_run="false",
        )
    ).json()
    assert report["summary"]["created"] == 0
    assert report["summary"]["name_mismatch"] == 1  # consolida el legajo 100001
    item = report["items"][0]
    assert item["status"] == "name_mismatch"
    assert item["student"]["last_name"] == "Gómez"

    listed = (
        await client.get(
            f"{URL}/{calendar_class['id_calendar_class']}/attendance", headers=admin
        )
    ).json()
    assert listed["items"][0]["present"] is False


async def test_unknown_and_not_enrolled(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    await _enroll(client, admin, ANA_ID, sy)
    await _new_student(client, admin, 100011, "Sofía", "Díaz")  # no se inscribe

    transcript = "\n".join(
        [
            "100011-DiazSofia",  # alumno no inscripto en el curso
            "200001-RodriguezMarta",  # legajo de una profesora
            "999999-NadieNadie",  # legajo inexistente
            "10001-GomezAna",  # legajo con un dígito de menos
        ]
    )
    report = (
        await _import_file(client, admin, calendar_class["id_calendar_class"], transcript)
    ).json()
    statuses = _statuses(report)
    assert statuses[100011] == "not_enrolled"
    assert statuses[200001] == "not_enrolled"
    assert statuses[999999] == "unknown_legajo"
    assert statuses[10001] == "unknown_legajo"


# ---------- CSV y texto pegado ----------
async def test_csv_file_with_header(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    juan = await _new_student(client, admin, 100010, "Juan Carlos", "Domínguez")
    await _enroll(client, admin, ANA_ID, sy)
    await _enroll(client, admin, juan["id_student"], sy)

    csv_text = "\n".join(
        [
            "legajo,apellido,nombre",
            "100001,Gómez,Ana",
            "100010,Domínguez,Juan Carlos",
            "abc,Invalido,Fila",
        ]
    )
    report = (
        await _import_file(
            client,
            admin,
            calendar_class["id_calendar_class"],
            csv_text,
            filename="lista.csv",
        )
    ).json()
    assert report["summary"]["would_create"] == 2
    assert report["summary"]["invalid"] == 1
    assert _statuses(report) == {100001: "would_create", 100010: "would_create"}


async def test_csv_text_with_semicolon(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    await _enroll(client, admin, ANA_ID, sy)

    report = (
        await _import_text(
            client,
            admin,
            calendar_class["id_calendar_class"],
            "100001;Gómez;Ana",
            fmt="csv",
        )
    ).json()
    assert report["summary"]["would_create"] == 1


async def test_file_with_bom_and_latin1(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    await _enroll(client, admin, ANA_ID, sy)

    bom = await _import_file(
        client,
        admin,
        calendar_class["id_calendar_class"],
        "\ufeff100001-GomezAna",
    )
    assert bom.status_code == 200
    assert bom.json()["summary"]["would_create"] == 1

    latin = await _import_file(
        client,
        admin,
        calendar_class["id_calendar_class"],
        "100001-GómezAna".encode("latin-1"),
    )
    assert latin.status_code == 200
    assert latin.json()["summary"]["would_create"] == 1


# ---------- errores ----------
async def test_errors(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await _sy(client, admin)
    calendar_class = await _class(client, admin, sy)
    url = f"{URL}/{calendar_class['id_calendar_class']}/attendance/import-transcript"

    assert (
        await client.post(url, files={"file": ("vacio.txt", b"", "text/plain")}, headers=admin)
    ).status_code == 422
    assert (
        await _import_file(client, admin, calendar_class["id_calendar_class"], "solo charla")
    ).status_code == 422
    assert (
        await client.post(
            f"{URL}/{calendar_class['id_calendar_class']}/attendance/import-transcript/text",
            json={"text": "100001-", "format": "text"},
            headers=admin,
        )
    ).status_code == 422
    too_large = b"x" * 2_000_001
    assert (
        await _import_file(
            client,
            admin,
            calendar_class["id_calendar_class"],
            too_large,
            filename="grande.txt",
        )
    ).status_code == 413
