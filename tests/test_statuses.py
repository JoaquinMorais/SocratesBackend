from typing import get_args

from models import Status
from models.state import (
    MEMBER_CODES,
    PROJECT_CATALOG,
    PROJECT_INITIAL,
    PROJECT_INSURED,
    STUDENT_PROJECT_CATALOG,
    STUDENT_PROJECT_INITIAL,
    STUDENT_PROJECT_ORDER,
    DELIVERY_CATALOG,
    DELIVERY_ORDER,
    STUDENT_SECTION_YEAR_CATALOG,
    STUDENT_SECTION_YEAR_ORDER,
    State,
    state_class,
    state_for,
)
from schemas.status import MembershipStatus
from tests.helpers import STUDENT, SUPER_ADMIN
from utils.statuses import (
    DEFAULT_STATUSES,
    is_insured,
    is_member,
    membership_initial_status,
)

URL = "/statuses"


def _catalog_codes(ambito: str) -> set[str]:
    return {s["code"] for s in DEFAULT_STATUSES if s["ambito"] == ambito}


def _state(ambito: str, code: str):
    return state_class(ambito, code)


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
        assert r.json()["total"] == 22


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
    body = (
        await client.get(
            URL, params={"ambito": "student_section_year"}, headers=headers
        )
    ).json()
    assert {i["code"] for i in body["items"]} == {
        "registered", "attending", "abandoned", "finished_approved", "finished_failed",
    }
    body = (
        await client.get(
            URL, params={"ambito": "delivery"}, headers=headers
        )
    ).json()
    assert {i["code"] for i in body["items"]} == {
        "requested", "pending_approval", "pending_modification", "approved",
    }


async def test_invalid_ambito_rejected(client, login):
    r = await client.get(URL, params={"ambito": "otro"}, headers=await login(STUDENT))
    assert r.status_code == 422


async def test_list_pagination(client, login):
    headers = await login(STUDENT)
    page1 = (await client.get(f"{URL}?limit=2", headers=headers)).json()
    assert len(page1["items"]) == 2 and page1["total"] == 22
    page2 = (await client.get(f"{URL}?limit=2&offset=2", headers=headers)).json()
    assert len(page2["items"]) == 2
    assert (await client.get(f"{URL}?limit=0", headers=headers)).status_code == 422


# ---------- jerarquía de estados (State) ----------
async def test_member_category():
    assert is_member("active") and is_member("finished")
    for code in ("pending_approval", "abandoned", "expelled", "rejected"):
        assert not is_member(code), code
    assert MEMBER_CODES == frozenset({"active", "finished"})
    assert {state.code for state in STUDENT_PROJECT_CATALOG if state.is_member} == MEMBER_CODES


async def test_insured_category():
    for code in ("in_idea", "in_progress", "pending_approval", "rejected"):
        assert is_insured(code), code
    for code in ("uninsured", "approved", "cancelled"):
        assert not is_insured(code), code
    for code in ("active", "abandoned", "finished", "expelled"):
        assert not is_insured(code), code
    assert PROJECT_INSURED == frozenset(
        {"in_idea", "in_progress", "pending_approval", "rejected"}
    )
    for state in PROJECT_CATALOG:
        assert is_insured(state.code) == state.is_insured


async def test_project_final_states():
    for code in ("approved", "cancelled"):
        item = next(
            s for s in DEFAULT_STATUSES
            if s["ambito"] == "project" and s["code"] == code
        )
        assert item["is_final"], code
        assert _state("project", code).next_codes == frozenset(), code


async def test_initial_and_pending_status():
    assert PROJECT_INITIAL == "uninsured"
    assert STUDENT_PROJECT_INITIAL == "active"
    assert membership_initial_status(has_leader=False) == "active"
    assert membership_initial_status(has_leader=True) == "pending_approval"


async def test_membership_transitions():
    pending = _state("student_project", "pending_approval")
    active = _state("student_project", "active")
    rejected = _state("student_project", "rejected")
    assert pending.can_transition_to("active")
    assert pending.can_transition_to("rejected")
    assert active.can_transition_to("abandoned")
    assert active.can_transition_to("expelled")
    assert active.can_transition_to("finished")
    assert rejected.can_transition_to("pending_approval")
    assert not active.can_transition_to("pending_approval")
    assert not active.can_transition_to("rejected")
    assert _state("student_project", "finished").next_codes == frozenset()


async def test_project_transitions():
    assert _state("project", "uninsured").can_transition_to("in_idea")
    assert _state("project", "in_idea").can_transition_to("in_progress")
    assert _state("project", "in_progress").can_transition_to("pending_approval")
    assert _state("project", "pending_approval").can_transition_to("approved")
    assert _state("project", "pending_approval").can_transition_to("rejected")
    assert _state("project", "rejected").can_transition_to("in_progress")
    assert _state("project", "in_progress").can_transition_to("uninsured")
    assert not _state("project", "approved").can_transition_to("cancelled")
    assert not _state("project", "cancelled").can_transition_to("uninsured")
    assert _state("project", "approved").next_codes == frozenset()
    assert _state("project", "cancelled").next_codes == frozenset()


async def test_final_states_have_no_transitions():
    for state in (
        *PROJECT_CATALOG,
        *STUDENT_PROJECT_CATALOG,
        *STUDENT_SECTION_YEAR_CATALOG,
        *DELIVERY_CATALOG,
    ):
        if state.is_final:
            assert state.next_codes == frozenset(), state.code


async def test_catalog_codes_match_states():
    for ambito, catalog in (
        ("project", PROJECT_CATALOG),
        ("student_project", STUDENT_PROJECT_CATALOG),
        ("student_section_year", STUDENT_SECTION_YEAR_CATALOG),
        ("delivery", DELIVERY_CATALOG),
    ):
        assert {state.code for state in catalog} == _catalog_codes(ambito)
        codes = {state.code for state in catalog}
        for state in catalog:
            assert state.next_codes <= codes, state.code


async def test_default_statuses_match_state_metadata():
    for item in DEFAULT_STATUSES:
        state = state_class(item["ambito"], item["code"])
        assert item["name"] == state.name
        assert item["description"] == state.description
        assert item["is_final"] == state.is_final


async def test_registry_maps_catalog_states():
    for state in (
        *PROJECT_CATALOG,
        *STUDENT_PROJECT_CATALOG,
        *STUDENT_SECTION_YEAR_CATALOG,
        *DELIVERY_CATALOG,
    ):
        row = Status(ambito=state.ambito, code=state.code, name=state.name)
        assert state_for(row) is state


async def test_unknown_state_falls_back_to_base():
    row = Status(ambito="project", code="custom", name="Custom")
    assert state_for(row) is State
    assert not State.can_transition_to("anything")


async def test_student_section_year_transitions():
    registered = _state("student_section_year", "registered")
    attending = _state("student_section_year", "attending")
    abandoned = _state("student_section_year", "abandoned")
    approved = _state("student_section_year", "finished_approved")
    failed = _state("student_section_year", "finished_failed")

    assert registered.next_codes == frozenset()
    assert attending.can_transition_to("abandoned")
    assert attending.can_transition_to("finished_approved")
    assert attending.can_transition_to("finished_failed")
    assert abandoned.can_transition_to("attending")
    assert failed.can_transition_to("attending")
    assert approved.next_codes == frozenset()
    assert {state.code for state in STUDENT_SECTION_YEAR_CATALOG} == set(
        STUDENT_SECTION_YEAR_ORDER
    )


async def test_delivery_transitions():
    requested = _state("delivery", "requested")
    pending = _state("delivery", "pending_approval")
    modification = _state("delivery", "pending_modification")
    approved = _state("delivery", "approved")

    assert requested.can_transition_to("pending_approval")
    assert pending.can_transition_to("pending_modification")
    assert pending.can_transition_to("approved")
    assert pending.can_transition_to("requested")
    assert modification.can_transition_to("pending_approval")
    assert approved.next_codes == frozenset()
    assert {state.code for state in DELIVERY_CATALOG} == set(DELIVERY_ORDER)


async def test_membership_status_literal_matches_order():
    assert set(get_args(MembershipStatus)) == set(STUDENT_PROJECT_ORDER)
