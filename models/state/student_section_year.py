from models.state.base import State, register


class StudentSectionYearState(State):
    """Estado de una fila de alumno + curso lectivo.

    `state` en la tabla es un espejo para los índices parciales; el estado
    canónico vive en `status` (`statuses.ambito == 'student_section_year'`).
    """

    ambito = "student_section_year"


@register
class Registered(StudentSectionYearState):
    code = "registered"
    name = "Anotado"
    description = "El alumno está inscripto en el curso lectivo."
    is_final = True
    next_codes = frozenset()


@register
class Attending(StudentSectionYearState):
    code = "attending"
    name = "Cursando"
    description = "El alumno cursa actualmente este curso lectivo."
    next_codes = frozenset(
        {"abandoned", "finished_approved", "finished_failed"}
    )


@register
class Abandoned(StudentSectionYearState):
    code = "abandoned"
    name = "Abandonada"
    description = "El alumno abandonó o fue expulsado de la cursada."
    next_codes = frozenset({"attending"})


@register
class FinishedApproved(StudentSectionYearState):
    code = "finished_approved"
    name = "Finalizada y aprobada"
    description = "El alumno terminó la cursada con el proyecto aprobado."
    is_final = True
    next_codes = frozenset()


@register
class FinishedFailed(StudentSectionYearState):
    code = "finished_failed"
    name = "Finalizada y desaprobada"
    description = "El proyecto se canceló o la cursada terminó desaprobada."
    next_codes = frozenset({"attending"})


REGISTERED = Registered.code
ATTENDING = Attending.code
ABANDONED = Abandoned.code
FINISHED_APPROVED = FinishedApproved.code
FINISHED_FAILED = FinishedFailed.code
STATES = frozenset(
    {REGISTERED, ATTENDING, ABANDONED, FINISHED_APPROVED, FINISHED_FAILED}
)
CURRENT_CURSADA_STATES = frozenset({ATTENDING})
HISTORICAL_CURSADA_STATES = frozenset(
    {ABANDONED, FINISHED_APPROVED, FINISHED_FAILED}
)

STUDENT_SECTION_YEAR_CATALOG = (
    Registered,
    Attending,
    Abandoned,
    FinishedApproved,
    FinishedFailed,
)
STUDENT_SECTION_YEAR_ORDER = tuple(
    state.code for state in STUDENT_SECTION_YEAR_CATALOG
)
STUDENT_SECTION_YEAR_INITIAL = Registered.code
