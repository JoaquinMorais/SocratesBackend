from utils.state.base import apply_transition


async def apply_comment_transition(db, comment, target_code: str):
    """Valida y aplica una transición de estado de un comentario."""
    return await apply_transition(db, comment, target_code, effector=None)
