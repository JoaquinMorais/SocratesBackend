import io
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image as PILImage

from config.settings import settings
from tests.helpers import STUDENT, SUPER_ADMIN

URL = "/images"


# ---------- generadores ----------
def _image_bytes(fmt: str, *, size: tuple[int, int] = (8, 8), alpha: bool = False) -> bytes:
    buf = io.BytesIO()
    mode = "RGBA" if alpha else "RGB"
    img = PILImage.new(mode, size, (0, 128, 255, 255) if alpha else (0, 128, 255))
    img.save(buf, format=fmt)
    return buf.getvalue()


PNG = _image_bytes("PNG", alpha=True)
JPEG = _image_bytes("JPEG")
WEBP = _image_bytes("WEBP")
GIF = _image_bytes("GIF")
BAD = b"esto no es una imagen"

TOO_LARGE = b"\x00" * (settings.IMAGE_MAX_BYTES + 1)


def _upload(client, headers, name: str, data: bytes, mime: str, field: str = "file"):
    return client.post(URL, files={field: (name, data, mime)}, headers=headers)


def _file_path(url: str) -> Path:
    # La URL es `MEDIA_BASE_URL` + "/" + key; el key no incluye el montaje `/media`.
    key = urlsplit(url).path.lstrip("/").removeprefix("media/")
    return Path(settings.MEDIA_DIR) / key


def _format_of(path: Path) -> str:
    with PILImage.open(path) as img:
        return img.format


# ---------- permisos ----------
async def test_requires_authentication(client):
    r = await _upload(client, None, "a.png", PNG, "image/png")
    assert r.status_code == 401, r.text
    assert (await client.get(f"{URL}/1")).status_code == 401
    assert (await client.delete(f"{URL}/1")).status_code == 401


async def test_student_cannot_write(client, login):
    headers = await login(STUDENT)
    r = await _upload(client, headers, "a.png", PNG, "image/png")
    assert r.status_code == 403, r.text
    r = await client.delete(f"{URL}/1", headers=headers)
    assert r.status_code == 403


async def test_professor_can_upload(client, login, make_professor):
    headers = await login(await make_professor("prof-img@frc.utn.edu.ar"))
    r = await _upload(client, headers, "a.png", PNG, "image/png")
    assert r.status_code == 201, r.text


# ---------- subir ----------
async def test_upload_converts_to_webp_and_saves_file(client, login):
    headers = await login(SUPER_ADMIN)
    for name, data, mime in (
        ("a.png", PNG, "image/png"),
        ("b.jpg", JPEG, "image/jpeg"),
        ("c.webp", WEBP, "image/webp"),
    ):
        r = await _upload(client, headers, name, data, mime)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["content_type"] == "image/webp"
        assert body["size_bytes"] > 0
        assert body["original_name"] == name
        assert body["url"].startswith("http://test/media/images/")
        path = _file_path(body["url"])
        assert path.exists()
        assert _format_of(path) == "WEBP"  # el guardado en disco es WebP


async def test_upload_metadata_and_get(client, login):
    headers = await login(SUPER_ADMIN)
    body = (await _upload(client, headers, "logo.png", PNG, "image/png")).json()
    got = await client.get(f"{URL}/{body['id_image']}", headers=await login(STUDENT))
    assert got.status_code == 200 and got.json() == body
    assert (await client.get(f"{URL}/999", headers=headers)).status_code == 404


async def test_upload_rejects_invalid_content(client, login):
    headers = await login(SUPER_ADMIN)
    for name, data, mime in (("x.gif", GIF, "image/gif"), ("t.png", BAD, "image/png")):
        r = await _upload(client, headers, name, data, mime)
        assert r.status_code == 422, (name, r.text)
    empty = await _upload(client, headers, "e.png", b"", "image/png")
    assert empty.status_code == 422


async def test_upload_rejects_too_large(client, login):
    r = await _upload(client, await login(SUPER_ADMIN), "big.png", TOO_LARGE, "image/png")
    assert r.status_code == 413, r.text


async def test_upload_original_name_is_sane(client, login):
    r = await _upload(client, await login(SUPER_ADMIN), "../ev il/na me..png", PNG, "image/png")
    assert r.status_code == 201, r.text
    assert r.json()["original_name"] == "na me..png"  # sin rutas ni "../"


# ---------- eliminar ----------
async def test_delete_image(client, login):
    headers = await login(SUPER_ADMIN)
    body = (await _upload(client, headers, "a.png", PNG, "image/png")).json()
    url = body["url"]
    assert (await client.delete(f"{URL}/{body['id_image']}", headers=headers)).status_code == 204
    assert not _file_path(url).exists()
    assert (await client.get(f"{URL}/{body['id_image']}", headers=headers)).status_code == 404
    assert (await client.delete(f"{URL}/{body['id_image']}", headers=headers)).status_code == 404


async def test_media_file_is_served_publicly(client, login):
    body = (
        await _upload(
            client, await login(SUPER_ADMIN), "public.png", PNG, "image/png"
        )
    ).json()
    path = urlsplit(body["url"]).path
    r = await client.get(path)
    assert r.status_code == 200
    assert r.content  # el archivo se sirve sin login desde /media
