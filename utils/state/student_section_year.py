from fastapi import HTTPException, status

from models.state import state_class
from models.state.student_section_year import ATTENDING, FinishedFailed
from utils.state.base import apply_transition

_AMBITO = "student_section_year"


async def apply_cursada_transition(
    db,
    cursada,
    target_code: str,
    *,
    allow_project_joins: bool = False,
):
    """Valida y aplica una transición de estado de una cursada.

    El estado canónico es `cursada.status`; `cursada.state` se mantiene como
    espejo para los índices parciales y compatibilidad.
    """
    source = state_class(_AMBITO, cursada.status.code)
    if (
        target_code == ATTENDING
        and source is FinishedFailed
        and not allow_project_joins
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This section year is already finished",
        )

    previous, target = await apply_transition(
        db, cursada, target_code, effector=None
    )
    cursada.state = target.code
    db.add(cursada)
    return previous, target
