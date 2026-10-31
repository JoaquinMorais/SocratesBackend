from fastapi import HTTPException, status

from models.state import state_class, state_for
from utils.statuses import get_status


def _subject(ambito: str) -> str:
    return {
        "project": "project",
        "student_section_year": "enrollment",
        "delivery": "delivery",
    }.get(ambito, "membership")


async def apply_transition(db, entity, target_code: str, *, effector):
    """Valida y aplica una transición de estado.

    Resuelve la clase del estado actual, verifica que `target_code` sea un destino
    válido y ejecuta el efecto de entrada (`on_enter`) del estado destino. No hace
    commit: el llamador decide cuándo confirmar y si registra historial.
    """
    source = state_for(entity.status)
    current = entity.status.code
    if not source.can_transition_to(target_code):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A {_subject(entity.status.ambito)} in '{current}' cannot change to "
            f"'{target_code}'",
        )

    previous = entity.status
    target = await get_status(db, entity.status.ambito, target_code)
    entity.status = target
    db.add(entity)
    await state_class(entity.status.ambito, target_code).on_enter(
        effector, entity, previous
    )
    return previous, target
