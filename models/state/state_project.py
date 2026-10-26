from models.state.base import State, register


class ProjectState(State):
    """Estado de un proyecto (`ambito` = `project`)."""

    ambito = "project"


@register
class Uninsured(ProjectState):
    code = "uninsured"
    name = "Desasegurado"
    description = "El grupo todavía no tiene una idea asegurada."
    next_codes = frozenset({"in_idea", "in_progress", "pending_approval", "rejected", "cancelled"})

    @classmethod
    async def on_enter(cls, effector, project, previous) -> None:
        await effector.save_insured_memory(project, previous)


@register
class InIdea(ProjectState):
    code = "in_idea"
    name = "En idea"
    description = "El grupo está trabajando en la idea del proyecto."
    is_insured = True
    next_codes = frozenset({"in_progress", "uninsured", "cancelled"})


@register
class InProgress(ProjectState):
    code = "in_progress"
    name = "En proceso"
    description = "El grupo está desarrollando el proyecto."
    is_insured = True
    next_codes = frozenset({"pending_approval", "uninsured", "cancelled"})


@register
class PendingApprovalProject(ProjectState):
    code = "pending_approval"
    name = "Pendiente de aprobación"
    description = "El proyecto espera la aprobación de un profesor."
    is_insured = True
    next_codes = frozenset({"rejected", "approved", "uninsured", "cancelled"})


@register
class RejectedProject(ProjectState):
    code = "rejected"
    name = "Rechazado"
    description = "La aprobación del proyecto fue rechazada."
    is_insured = True
    next_codes = frozenset({"in_progress", "uninsured", "cancelled"})


@register
class Approved(ProjectState):
    code = "approved"
    name = "Aprobado"
    description = "El proyecto fue aprobado."
    is_final = True

    @classmethod
    async def on_enter(cls, effector, project, previous) -> None:
        await effector.finish_memberships(project)


@register
class Cancelled(ProjectState):
    code = "cancelled"
    name = "Cancelado"
    description = "El grupo se disolvió o el proyecto no se llevó a cabo."
    is_final = True

    @classmethod
    async def on_enter(cls, effector, project, previous) -> None:
        await effector.abandon_memberships(project)


PROJECT_CATALOG = (
    Uninsured,
    InIdea,
    InProgress,
    PendingApprovalProject,
    RejectedProject,
    Approved,
    Cancelled,
)
PROJECT_INITIAL = Uninsured.code
PROJECT_ORDER = tuple(state.code for state in PROJECT_CATALOG)
PROJECT_INSURED = frozenset(state.code for state in PROJECT_CATALOG if state.is_insured)
