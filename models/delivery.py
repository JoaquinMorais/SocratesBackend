from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

from models.activity import Activity
from models.project import Project
from models.status import Status


class Delivery(SQLModel, table=True):
    """Entrega de un proyecto para una actividad del mismo curso lectivo.

    Las filas se pre-crean para cada combinación proyecto × actividad; al
    enviarse se completa el link y, más adelante, las notas.
    """

    __tablename__ = "deliveries"
    __table_args__ = (
        UniqueConstraint(
            "id_project", "id_activity", name="uq_delivery_project_activity"
        ),
        CheckConstraint(
            "activity_grade IS NULL OR (activity_grade >= 1 AND activity_grade <= 100)",
            name="ck_delivery_activity_grade",
        ),
        CheckConstraint(
            "development_grade IS NULL OR (development_grade >= 1 AND development_grade <= 100)",
            name="ck_delivery_development_grade",
        ),
    )

    id_delivery: int | None = Field(default=None, primary_key=True)
    id_project: int = Field(
        foreign_key="projects.id_project",
        index=True,
        ondelete="CASCADE",
    )
    id_activity: int = Field(
        foreign_key="activities.id_activity",
        index=True,
        ondelete="CASCADE",
    )
    id_status: int = Field(foreign_key="statuses.id_status", index=True)
    link: str | None = Field(default=None, max_length=1000)
    activity_grade: int | None = Field(default=None)
    development_grade: int | None = Field(default=None)
    submitted_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )
    updated_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )

    status: Status = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
    project: Project = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
    activity: Activity = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
