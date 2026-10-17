from tests.helpers import STUDENT, SUPER_ADMIN

URL = "/statuses"


async def test_requires_authentication(client):
    assert (await client.get(URL)).status_code == 401


async def test_any_user_can_list_statuses(client, login, make_professor):
    headers_list = [
        await login(STUDENT),
        await login(SUPER_ADMIN),
        await login(await make_professor("prof@frc.utn.edu.ar")),
    ]
    for headers in headers_list:
        r = await client.get(URL, headers=headers)
        assert r.status_code == 200
        assert r.json()["total"] == 8


async def test_list_returns_public_fields(client, login):
    body = (await client.get(URL, headers=await login(STUDENT))).json()
    assert set(body["items"][0]) == {
        "id_status", "ambito", "code", "name", "description", "is_final",
    }


async def test_filter_by_ambito(client, login):
    headers = await login(STUDENT)
    body = (await client.get(URL, params={"ambito": "project"}, headers=headers)).json()
    assert body["total"] == 2
    assert {i["ambito"] for i in body["items"]} == {"project"}
    assert {i["code"] for i in body["items"]} == {"active", "cancelled"}
    body = (
        await client.get(URL, params={"ambito": "student_project"}, headers=headers)
    ).json()
    assert {i["code"] for i in body["items"]} == {
        "active", "pending_approval", "abandoned", "finished", "expelled", "rejected",
    }


async def test_invalid_ambito_rejected(client, login):
    r = await client.get(URL, params={"ambito": "otro"}, headers=await login(STUDENT))
    assert r.status_code == 422


async def test_list_pagination(client, login):
    headers = await login(STUDENT)
    page1 = (await client.get(f"{URL}?limit=2", headers=headers)).json()
    assert len(page1["items"]) == 2 and page1["total"] == 8
    page2 = (await client.get(f"{URL}?limit=2&offset=2", headers=headers)).json()
    assert len(page2["items"]) == 2
    assert (await client.get(f"{URL}?limit=0", headers=headers)).status_code == 422
