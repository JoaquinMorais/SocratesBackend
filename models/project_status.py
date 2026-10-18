from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlmodel import Field, Relationship, SQLModel

from models.status import Status


class ProjectStatus(SQLModel, table=True):
    """Historial de estados de un proyecto: cada fila registra una transición.

    `id_status_from` en `NULL` significa la creación del proyecto.
    """

    __tablename__ = "project_statuses"

    id_project_status: int | None = Field(default=None, primary_key=True)
    # El historial vive y muere con el proyecto: no debe impedir su eliminación.
    id_project: int = Field(
        foreign_key="projects.id_project", index=True, ondelete="CASCADE"
    )
    id_status_from: int | None = Field(default=None, foreign_key="statuses.id_status")
    id_status_to: int = Field(foreign_key="statuses.id_status", index=True)
    changed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )

    status_from: Status | None = Relationship(
        sa_relationship_kwargs={
            "lazy": "selectin",
            "foreign_keys": "[ProjectStatus.id_status_from]",
        }
    )
    status_to: Status = Relationship(
        sa_relationship_kwargs={
            "lazy": "selectin",
            "foreign_keys": "[ProjectStatus.id_status_to]",
        }
    )
