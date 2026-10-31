from models.state.base import State, register
from models.state.student_section_year import ABANDONED, FINISHED_APPROVED


class StudentProjectState(State):
    """Estado de una membresía alumno-proyecto (`ambito` = `student_project`)."""

    ambito = "student_project"


@register
class Active(StudentProjectState):
    code = "active"
    name = "Activo"
    description = "El alumno integra el grupo."
    is_member = True
    next_codes = frozenset({"abandoned", "expelled", "finished"})

    @classmethod
    async def on_enter(cls, effector, membership, previous) -> None:
        await effector.reject_other_pending(membership)
        await effector.enter_cursada(membership)


@register
class PendingApprovalMember(StudentProjectState):
    code = "pending_approval"
    name = "Pendiente de aprobación"
    description = "El alumno solicitó unirse y espera la aprobación del jefe del grupo o de un profesor."
    next_codes = frozenset({"active", "rejected"})


@register
class Abandoned(StudentProjectState):
    code = "abandoned"
    name = "Abandono"
    description = "El alumno dejó el grupo antes de terminar el cursado."
    is_final = True

    @classmethod
    async def on_enter(cls, effector, membership, previous) -> None:
        await effector.close_cursada(membership, ABANDONED)
        await effector.promote_successor(membership)


@register
class Finished(StudentProjectState):
    code = "finished"
    name = "Finalizado"
    description = "El proyecto terminó y la participación quedó cerrada."
    is_final = True
    is_member = True

    @classmethod
    async def on_enter(cls, effector, membership, previous) -> None:
        await effector.close_cursada(membership, FINISHED_APPROVED)


@register
class Expelled(StudentProjectState):
    code = "expelled"
    name = "Expulsado"
    description = "Un profesor sacó al alumno del grupo."
    is_final = True

    @classmethod
    async def on_enter(cls, effector, membership, previous) -> None:
        await effector.close_cursada(membership, ABANDONED)
        await effector.promote_successor(membership)


@register
class RejectedMember(StudentProjectState):
    code = "rejected"
    name = "Rechazado"
    description = "La solicitud de incorporación fue rechazada."
    next_codes = frozenset({"pending_approval"})


STUDENT_PROJECT_CATALOG = (
    Active,
    PendingApprovalMember,
    Abandoned,
    Finished,
    Expelled,
    RejectedMember,
)
STUDENT_PROJECT_ORDER = (
    Active.code,
    PendingApprovalMember.code,
    Finished.code,
    Abandoned.code,
    Expelled.code,
    RejectedMember.code,
)
STUDENT_PROJECT_INITIAL = Active.code
STUDENT_PROJECT_PENDING = PendingApprovalMember.code
MEMBER_CODES = frozenset(state.code for state in STUDENT_PROJECT_CATALOG if state.is_member)
