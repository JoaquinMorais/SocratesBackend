from models.state.base import State, register


class DeliveryState(State):
    """Estado de una entrega de proyecto (`ambito` = `delivery`)."""

    ambito = "delivery"


@register
class RequestedDelivery(DeliveryState):
    code = "requested"
    name = "Solicitada"
    description = "La entrega existe pero el grupo todavía no la envió."
    next_codes = frozenset({"pending_approval"})


@register
class PendingApprovalDelivery(DeliveryState):
    code = "pending_approval"
    name = "Pendiente de aprobación"
    description = "El grupo entregó y espera la revisión del profesor."
    next_codes = frozenset({"pending_modification", "approved", "requested"})


@register
class PendingModificationDelivery(DeliveryState):
    code = "pending_modification"
    name = "Pendiente de modificación"
    description = "El profesor rechazó la entrega y el grupo debe corregirla."
    next_codes = frozenset({"pending_approval"})


@register
class ApprovedDelivery(DeliveryState):
    code = "approved"
    name = "Aprobada"
    description = "La entrega fue aprobada."
    is_final = True
    next_codes = frozenset()


DELIVERY_CATALOG = (
    RequestedDelivery,
    PendingApprovalDelivery,
    PendingModificationDelivery,
    ApprovedDelivery,
)
DELIVERY_ORDER = tuple(state.code for state in DELIVERY_CATALOG)
DELIVERY_INITIAL = RequestedDelivery.code
REQUESTED = RequestedDelivery.code
PENDING_APPROVAL = PendingApprovalDelivery.code
PENDING_MODIFICATION = PendingModificationDelivery.code
APPROVED = ApprovedDelivery.code
