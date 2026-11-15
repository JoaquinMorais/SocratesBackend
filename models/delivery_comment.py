from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime
from sqlmodel import Field, Relationship, SQLModel

from models.delivery import Delivery
from models.professor import Professor
from models.status import Status


class DeliveryComment(SQLModel, table=True):
    """Comentario de una entrega: feedback para el grupo o anotación interna."""

    __tablename__ = "delivery_comments"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('feedback', 'annotation')",
            name="ck_delivery_comment_kind",
        ),
    )

    id_delivery_comment: int | None = Field(default=None, primary_key=True)
    id_delivery: int = Field(
        foreign_key="deliveries.id_delivery", index=True, ondelete="CASCADE"
    )
    id_professor: int = Field(
        foreign_key="professors.id_professor", index=True
    )
    kind: str = Field(default="feedback", max_length=20)
    content: str = Field(max_length=2000)
    id_status: int = Field(foreign_key="statuses.id_status", index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )
    corrected_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )

    delivery: Delivery = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
    professor: Professor = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"}
    )
    status: Status = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
