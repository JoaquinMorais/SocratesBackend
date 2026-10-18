from typing import get_args

from schemas.status import MembershipStatus
from tests.helpers import STUDENT, SUPER_ADMIN
from utils.statuses import (
    DEFAULT_STATUSES,
    INSURED,
    MEMBER,
    POLICIES,
    PROJECT,
    STUDENT_PROJECT,
    is_insured,
    is_member,
    membership_initial_status,
)

URL = "/statuses"


def _catalog_codes(ambito: str) -> set[str]:
    return {s["code"] for s in DEFAULT_STATUSES if s["ambito"] == ambito}


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
        assert r.json()["total"] == 13


async def test_list_returns_public_fields(client, login):
    body = (await client.get(URL, headers=await login(STUDENT))).json()
    assert set(body["items"][0]) == {
        "id_status", "ambito", "code", "name", "description", "is_final", "is_insured",
    }


async def test_filter_by_ambito(client, login):
    headers = await login(STUDENT)
    body = (await client.get(URL, params={"ambito": "project"}, headers=headers)).json()
    assert body["total"] == 7
    assert {i["ambito"] for i in body["items"]} == {"project"}
    assert {i["code"] for i in body["items"]} == {
        "uninsured", "in_idea", "in_progress", "pending_approval",
        "rejected", "approved", "cancelled",
    }
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
    assert len(page1["items"]) == 2 and page1["total"] == 13
    page2 = (await client.get(f"{URL}?limit=2&offset=2", headers=headers)).json()
    assert len(page2["items"]) == 2
    assert (await client.get(f"{URL}?limit=0", headers=headers)).status_code == 422


# ---------- reglas por ámbito (StatusPolicy) ----------
async def test_member_category():
    assert is_member("active") and is_member("finished")
    for code in ("pending_approval", "abandoned", "expelled", "rejected"):
        assert not is_member(code), code
    assert STUDENT_PROJECT.codes_of(MEMBER) == frozenset({"active", "finished"})


async def test_insured_category():
    for code in ("in_idea", "in_progress", "pending_approval", "rejected"):
        assert is_insured(code), code
    for code in ("uninsured", "approved", "cancelled"):
        assert not is_insured(code), code
    for code in ("active", "abandoned", "finished", "expelled"):
        assert not is_insured(code), code
    assert PROJECT.codes_of(INSURED) == frozenset(
        {"in_idea", "in_progress", "pending_approval", "rejected"}
    )


async def test_project_final_states():
    for code in ("approved", "cancelled"):
        item = next(
            s for s in DEFAULT_STATUSES
            if s["ambito"] == "project" and s["code"] == code
        )
        assert item["is_final"], code
        assert PROJECT.next_codes(code) == frozenset(), code


async def test_initial_and_pending_status():
    assert PROJECT.initial == "uninsured"
    assert STUDENT_PROJECT.initial == "active"
    assert membership_initial_status(has_leader=False) == "active"
    assert membership_initial_status(has_leader=True) == "pending_approval"


async def test_transitions():
    assert STUDENT_PROJECT.can_transition("pending_approval", "active")
    assert STUDENT_PROJECT.can_transition("pending_approval", "rejected")
    assert STUDENT_PROJECT.can_transition("active", "abandoned")
    assert STUDENT_PROJECT.can_transition("active", "expelled")
    assert STUDENT_PROJECT.can_transition("active", "finished")
    assert STUDENT_PROJECT.can_transition("rejected", "pending_approval")
    assert not STUDENT_PROJECT.can_transition("active", "pending_approval")
    assert not STUDENT_PROJECT.can_transition("active", "rejected")
    assert STUDENT_PROJECT.next_codes("finished") == frozenset()


async def test_project_transitions():
    assert PROJECT.can_transition("uninsured", "in_idea")
    assert PROJECT.can_transition("in_idea", "in_progress")
    assert PROJECT.can_transition("in_progress", "pending_approval")
    assert PROJECT.can_transition("pending_approval", "approved")
    assert PROJECT.can_transition("pending_approval", "rejected")
    assert PROJECT.can_transition("rejected", "in_progress")
    assert PROJECT.can_transition("in_progress", "uninsured")
    assert not PROJECT.can_transition("approved", "cancelled")
    assert not PROJECT.can_transition("cancelled", "uninsured")
    assert PROJECT.next_codes("approved") == frozenset()
    assert PROJECT.next_codes("cancelled") == frozenset()


async def test_final_states_have_no_transitions():
    for item in DEFAULT_STATUSES:
        if item["is_final"]:
            policy = POLICIES[item["ambito"]]
            assert policy.next_codes(item["code"]) == frozenset(), item["code"]


async def test_policy_codes_match_catalog():
    for ambito, policy in POLICIES.items():
        assert set(policy.order) == _catalog_codes(ambito)
        codes = set(policy.order)
        for category in policy.categories:
            assert policy.codes_of(category) <= codes, category
        for code, targets in policy.transitions.items():
            assert code in codes, code
            assert targets <= codes, code


async def test_membership_status_literal_matches_policy():
    assert set(get_args(MembershipStatus)) == set(STUDENT_PROJECT.order)
