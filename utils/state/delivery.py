from utils.state.base import apply_transition


async def apply_delivery_transition(db, delivery, target_code: str):
    """Valida y aplica una transición de estado de una entrega."""
    return await apply_transition(db, delivery, target_code, effector=None)
