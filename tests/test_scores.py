from tests.helpers import STUDENT, SUPER_ADMIN, assign_professor, section_year

URL = "/section-years"
DEFAULT_SCORES = {
    "excellent": ("Excelente", 100),
    "very_good_plus": ("Muy Bueno +", 90),
    "very_good": ("Muy Bueno", 80),
    "good": ("Bueno", 65),
    "regular": ("Regular", 55),
    "incomplete": ("Incompleto", 30),
}


async def _scores(client, headers, id_section_year: int):
    return await client.get(
        f"{URL}/{id_section_year}/scores", headers=headers
    )


async def _patch_scores(client, headers, id_section_year: int, scores: list[dict]):
    return await client.patch(
        f"{URL}/{id_section_year}/scores",
        json={"scores": scores},
        headers=headers,
    )


async def test_scores_requires_authentication(client):
    assert (await client.get(f"{URL}/1/scores")).status_code == 401
    assert (
        await client.patch(f"{URL}/1/scores", json={"scores": []})
    ).status_code == 401


async def test_scores_permissions(client, login, make_professor):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2026)
    assert (await _scores(client, await login(STUDENT), sy)).status_code == 403

    other = await make_professor("prof-scores-otro@frc.utn.edu.ar")
    assert (await _scores(client, await login(other), sy)).status_code == 403
    assert (
        await _patch_scores(
            client, await login(other), sy, [{"code": "good", "value": 60}]
        )
    ).status_code == 403

    assigned = await make_professor("prof-scores@frc.utn.edu.ar", legajo=300006)
    await assign_professor(client, admin, assigned, sy)
    assert (await _scores(client, await login(assigned), sy)).status_code == 200
    assert (
        await _patch_scores(
            client, await login(assigned), sy, [{"code": "good", "value": 60}]
        )
    ).status_code == 200
    assert (await _scores(client, admin, sy)).status_code == 200


async def test_scores_defaults_and_update(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2026)

    body = (await _scores(client, admin, sy)).json()
    by_code = {item["code"]: item for item in body["items"]}
    assert set(by_code) == set(DEFAULT_SCORES)
    for code, (name, value) in DEFAULT_SCORES.items():
        assert by_code[code]["name"] == name
        assert by_code[code]["value"] == value

    r = await _patch_scores(
        client,
        admin,
        sy,
        [
            {"code": "excellent", "value": 100},
            {"code": "very_good_plus", "value": 95},
        ],
    )
    assert r.status_code == 200, r.text
    by_code = {item["code"]: item for item in r.json()["items"]}
    assert by_code["very_good_plus"]["value"] == 95
    assert by_code["good"]["value"] == 65


async def test_scores_validation(client, login):
    admin = await login(SUPER_ADMIN)
    sy = await section_year(client, admin, "3K1", 2026)
    assert (
        await _patch_scores(client, admin, sy, [{"code": "nope", "value": 50}])
    ).status_code == 422
    assert (
        await _patch_scores(
            client,
            admin,
            sy,
            [{"code": "good", "value": 50}, {"code": "good", "value": 60}],
        )
    ).status_code == 422
    assert (
        await _patch_scores(client, admin, sy, [{"code": "good", "value": 0}])
    ).status_code == 422
    assert (
        await _patch_scores(client, admin, sy, [{"code": "good", "value": 101}])
    ).status_code == 422
    assert (
        await _patch_scores(client, admin, sy, [{"code": "good", "value": 50, "extra": 1}])
    ).status_code == 422
    assert (await _patch_scores(client, admin, sy, [])).status_code == 422
    assert (
        await client.patch(
            f"{URL}/{sy}/scores", json={"other": []}, headers=admin
        )
    ).status_code == 422
