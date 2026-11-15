from models.state.base import State, register


class DeliveryCommentState(State):
    """Estado de un comentario de entrega (`ambito` = `delivery_comment`)."""

    ambito = "delivery_comment"


@register
class RequestedComment(DeliveryCommentState):
    code = "requested"
    name = "Solicitado"
    description = "El profesor dejó feedback pendiente de corrección."
    next_codes = frozenset({"corrected"})


@register
class CorrectedComment(DeliveryCommentState):
    code = "corrected"
    name = "Corregido"
    description = "El alumno o el staff marcaron el feedback como corregido."
    is_final = True
    next_codes = frozenset()


@register
class Annotation(DeliveryCommentState):
    code = "annotation"
    name = "Anotación"
    description = "Nota interna del staff, sin flujo de corrección."
    is_final = True
    next_codes = frozenset()


DELIVERY_COMMENT_CATALOG = (
    RequestedComment,
    CorrectedComment,
    Annotation,
)
DELIVERY_COMMENT_ORDER = tuple(state.code for state in DELIVERY_COMMENT_CATALOG)
DELIVERY_COMMENT_INITIAL = RequestedComment.code
REQUESTED_COMMENT = RequestedComment.code
CORRECTED_COMMENT = CorrectedComment.code
ANNOTATION = Annotation.code
FEEDBACK_KIND = "feedback"
ANNOTATION_KIND = "annotation"
