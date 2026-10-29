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


# ---------- imagen (funcionalidad de imagen en tecnologías) ----------
import io
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image as PILImage

from config.settings import settings
from tests.test_images import BAD, JPEG, PNG


def _fmultipart(name: str, data: bytes, mime: str):
    return {"file": (name, data, mime)}


def _file_path(url: str) -> Path:
    # La URL es `MEDIA_BASE_URL` + "/" + key; el key no incluye el montaje `/media`.
    key = urlsplit(url).path.lstrip("/").removeprefix("media/")
    return Path(settings.MEDIA_DIR) / key


def _raw_multipart(fields: dict[str, str], boundary: str = "socrates-test") -> bytes:
    lines = []
    for key, value in fields.items():
        lines += [f"--{boundary}", f'Content-Disposition: form-data; name="{key}"', "", value]
    lines += [f"--{boundary}--", ""]
    return "\r\n".join(lines).encode()


# permisos de los endpoints de imagen de tecnología
async def test_image_endpoints_require_auth(client):
    r = await client.put(f"{URL}/1/image", files=_fmultipart("a.png", PNG, "image/png"))
    assert r.status_code == 401
    assert (await client.delete(f"{URL}/1/image")).status_code == 401


async def test_image_endpoints_forbidden_for_student(client, login):
    headers = await login(STUDENT)
    r = await client.put(f"{URL}/1/image", files=_fmultipart("a.png", PNG, "image/png"), headers=headers)
    assert r.status_code == 403
    r = await client.delete(f"{URL}/1/image", headers=headers)
    assert r.status_code == 403


# crear con imagen (JSON id_image y multipart file)
async def test_create_with_uploaded_image_via_json(client, login):
    headers = await login(SUPER_ADMIN)
    image = (await client.post("/images", files=_fmultipart("logo.png", PNG, "image/png"), headers=headers)).json()
    r = await client.post(URL, json={"name": "React", "id_image": image["id_image"]}, headers=headers)
    assert r.status_code == 201, r.text
    assert r.json()["image"] == image  # el objeto imagen completo


async def test_create_multipart_with_file(client, login):
    r = await client.post(
        URL, data={"name": "Vue", "description": " Framework"}, files=_fmultipart("vue.png", JPEG, "image/jpeg"),
        headers=await login(SUPER_ADMIN),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Vue" and body["description"] == " Framework"
    img = body["image"]
    assert img["content_type"] == "image/webp" and img["original_name"] == "vue.png"
    assert _file_path(img["url"]).exists()


async def test_create_multipart_without_file(client, login):
    headers = await login(SUPER_ADMIN)
    r = await client.post(
        URL,
        content=_raw_multipart({"name": "Svelte"}),
        headers={"content-type": "multipart/form-data; boundary=socrates-test", **headers},
    )
    assert r.status_code == 201, r.text
    assert r.json()["image"] is None


async def test_create_multipart_missing_name(client, login):
    headers = await login(SUPER_ADMIN)
    r = await client.post(
        URL,
        content=_raw_multipart({"description": "sin nombre"}),
        headers={"content-type": "multipart/form-data; boundary=socrates-test", **headers},
    )
    assert r.status_code == 422, r.text


async def test_create_multipart_bad_file_creates_nothing(client, login):
    headers = await login(SUPER_ADMIN)
    r = await client.post(URL, data={"name": "BadB"}, files=_fmultipart("a.png", BAD, "image/png"), headers=headers)
    assert r.status_code == 422, r.text
    listing = (await client.get(URL, params={"q": "BadB"}, headers=headers)).json()
    assert listing["total"] == 0  # no queda ni la tecnología ni el archivo


async def test_create_json_unknown_image_404_and_taken_409(client, login):
    headers = await login(SUPER_ADMIN)
    assert (await client.post(URL, json={"name": "X", "id_image": 999}, headers=headers)).status_code == 404
    image = (await client.post("/images", files=_fmultipart("l.png", PNG, "image/png"), headers=headers)).json()
    other = (await client.post("/technologies", json={"name": "Other"}, headers=headers)).json()
    # La imagen queda asignada a "Other"; reusarla en otra tecnología es 409.
    r = await client.patch(f"{URL}/{other['id_technology']}", json={"id_image": image["id_image"]}, headers=headers)
    assert r.status_code == 200, r.text
    r = await client.post(URL, json={"name": "X2", "id_image": image["id_image"]}, headers=headers)
    assert r.status_code == 409, r.text
    # y la tecnología que la tiene sigue con su imagen
    assert (await client.get(f"{URL}/{other['id_technology']}", headers=headers)).json()["image"] == image


# modificar con imagen
async def test_patch_multipart_file_replaces_and_deletes_previous(client, login):
    headers = await login(SUPER_ADMIN)
    tech = (await client.post(URL, data={"name": "Re"}, files=_fmultipart("a.png", PNG, "image/png"), headers=headers)).json()
    old_url = tech["image"]["url"]
    r = await client.patch(
        f"{URL}/{tech['id_technology']}",
        data={}, files=_fmultipart("b.png", JPEG, "image/jpeg"), headers=headers,
    )
    assert r.status_code == 200, r.text
    new_img = r.json()["image"]
    assert new_img["url"] != old_url
    assert not _file_path(old_url).exists()  # la anterior se borró del disco
    assert (await client.get(f"/images/{tech['image']['id_image']}", headers=headers)).status_code == 404


async def test_patch_json_without_image_fields_keeps_image(client, login):
    headers = await login(SUPER_ADMIN)
    tech = (await client.post(URL, data={"name": "Ke"}, files=_fmultipart("keep.png", PNG, "image/png"), headers=headers)).json()
    r = await client.patch(f"{URL}/{tech['id_technology']}", json={"name": "Kept"}, headers=headers)
    assert r.status_code == 200 and r.json()["image"] == tech["image"]


async def test_patch_null_id_image_does_not_detach(client, login):
    headers = await login(SUPER_ADMIN)
    tech = (await client.post(URL, data={"name": "Nu"}, files=_fmultipart("n.png", PNG, "image/png"), headers=headers)).json()
    r = await client.patch(f"{URL}/{tech['id_technology']}", json={"id_image": None}, headers=headers)
    assert r.status_code == 200 and r.json()["image"] == tech["image"]  # null = no enviado


async def test_put_route_replaces_previous_image(client, login):
    headers = await login(SUPER_ADMIN)
    tech = await _create(client, headers, "Putt")
    r = await client.put(f"{URL}/{tech['id_technology']}/image", files=_fmultipart("p.png", PNG, "image/png"), headers=headers)
    assert r.status_code == 200, r.text
    first = r.json()["image"]
    r = await client.put(f"{URL}/{tech['id_technology']}/image", files=_fmultipart("q.jpg", JPEG, "image/jpeg"), headers=headers)
    second = r.json()["image"]
    assert second["url"] != first["url"]
    assert not _file_path(first["url"]).exists()


async def test_delete_technology_image_route(client, login):
    headers = await login(SUPER_ADMIN)
    r = await client.post(URL, data={"name": "Qu"}, files=_fmultipart("q.png", JPEG, "image/jpeg"), headers=headers)
    tech = r.json()
    img_id, img_url = tech["image"]["id_image"], tech["image"]["url"]
    assert (await client.delete(f"{URL}/{tech['id_technology']}/image", headers=headers)).status_code == 204
    assert not _file_path(img_url).exists()
    assert (await client.get(f"/images/{img_id}", headers=headers)).status_code == 404
    assert (await client.get(f"{URL}/{tech['id_technology']}", headers=headers)).json()["image"] is None
    # sin imagen: 404
    assert (await client.delete(f"{URL}/{tech['id_technology']}/image", headers=headers)).status_code == 404


async def test_delete_technology_deletes_its_image(client, login):
    headers = await login(SUPER_ADMIN)
    tech = (await client.post(URL, data={"name": "De"}, files=_fmultipart("d.png", PNG, "image/png"), headers=headers)).json()
    img_id, img_url = tech["image"]["id_image"], tech["image"]["url"]
    assert (await client.delete(f"{URL}/{tech['id_technology']}", headers=headers)).status_code == 204
    assert not _file_path(img_url).exists()
    assert (await client.get(f"/images/{img_id}", headers=headers)).status_code == 404


async def test_delete_image_in_use_by_technology_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    r = await client.post(URL, data={"name": "Us"}, files=_fmultipart("u.png", PNG, "image/png"), headers=headers)
    tech = r.json()
    image_id = tech["image"]["id_image"]
    r = await client.delete(f"/images/{image_id}", headers=headers)
    assert r.status_code == 409, r.text  # primero hay que quitarla de la tecnología


async def test_unsupported_content_type_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    r = await client.post(
        URL,
        content=b"name=React",
        headers={"content-type": "application/x-www-form-urlencoded", **headers},
    )
    assert r.status_code == 422, r.text  # body JSON inválido



async def test_patch_json_replaces_image_and_deletes_previous(client, login):
    headers = await login(SUPER_ADMIN)
    tech = (
        await client.post(
            URL,
            data={"name": "JsonReplace"},
            files=_fmultipart("a.png", PNG, "image/png"),
            headers=headers,
        )
    ).json()
    old_image = tech["image"]
    image = (
        await client.post(
            "/images", files=_fmultipart("b.png", JPEG, "image/jpeg"), headers=headers
        )
    ).json()

    r = await client.patch(
        f"{URL}/{tech['id_technology']}",
        json={"id_image": image["id_image"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["image"] == image
    assert not _file_path(old_image["url"]).exists()
    assert (
        await client.get(f"/images/{old_image['id_image']}", headers=headers)
    ).status_code == 404


async def test_patch_json_image_taken_by_another_rejected(client, login):
    headers = await login(SUPER_ADMIN)
    owner = (
        await client.post(
            URL,
            data={"name": "Owner"},
            files=_fmultipart("o.png", PNG, "image/png"),
            headers=headers,
        )
    ).json()
    other = await _create(client, headers, "Otro")

    r = await client.patch(
        f"{URL}/{other['id_technology']}",
        json={"id_image": owner["image"]["id_image"]},
        headers=headers,
    )
    assert r.status_code == 409, r.text
    assert (
        await client.get(f"{URL}/{other['id_technology']}", headers=headers)
    ).json()["image"] is None


async def test_put_image_errors(client, login):
    headers = await login(SUPER_ADMIN)
    assert (
        await client.put(
            f"{URL}/999/image",
            files=_fmultipart("a.png", PNG, "image/png"),
            headers=headers,
        )
    ).status_code == 404

    tech = await _create(client, headers, "PutErrors")
    r = await client.put(
        f"{URL}/{tech['id_technology']}/image",
        files=_fmultipart("bad.png", BAD, "image/png"),
        headers=headers,
    )
    assert r.status_code == 422, r.text
