from typing import ClassVar

from sqlmodel import SQLModel


class State(SQLModel):
    """Estado de dominio: reglas estables de un `(ambito, code)`.

    No se persiste como tabla: `Status` guarda el catálogo en la BD y este árbol
    de clases aporta las transiciones válidas y los efectos al entrar. La seed
    puede sumar estados, pero solo los definidos acá tienen reglas; el resto cae
    en esta clase base, que no admite transiciones.
    """

    ambito: ClassVar[str] = ""
    code: ClassVar[str] = ""
    name: ClassVar[str] = ""
    description: ClassVar[str | None] = None
    is_final: ClassVar[bool] = False
    is_member: ClassVar[bool] = False
    is_insured: ClassVar[bool] = False
    next_codes: ClassVar[frozenset[str]] = frozenset()

    @classmethod
    def can_transition_to(cls, code: str) -> bool:
        """Si desde este estado se puede pasar a `code`."""
        return code in cls.next_codes

    @classmethod
    async def on_enter(cls, effector, entity, previous) -> None:
        """Efecto al entrar al estado. `effector` aplica los cambios en la BD."""
        return None


_REGISTRY: dict[tuple[str, str], type[State]] = {}


def register(cls: type[State]) -> type[State]:
    """Registra una clase concreta por `(ambito, code)`."""
    _REGISTRY[(cls.ambito, cls.code)] = cls
    return cls


def state_for(status) -> type[State]:
    """Clase de estado para una fila `Status`; la base si no está registrada."""
    return _REGISTRY.get((status.ambito, status.code), State)


def state_class(ambito: str, code: str) -> type[State]:
    """Clase registrada para `(ambito, code)`; la base si no existe."""
    return _REGISTRY.get((ambito, code), State)
