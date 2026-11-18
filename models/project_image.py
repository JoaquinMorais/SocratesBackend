from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlmodel import Field, Relationship, SQLModel

from models.image import Image
from models.project import Project


class ProjectImage(SQLModel, table=True):
    """Logo exclusivo de un proyecto (relación 1 a 1 mediante tabla intermedia)."""

    __tablename__ = "project_images"

    id_project: int = Field(
        foreign_key="projects.id_project",
        primary_key=True,
        ondelete="CASCADE",
    )
    id_image: int = Field(
        foreign_key="images.id_image",
        unique=True,
        index=True,
        ondelete="RESTRICT",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
    )

    project: Project = Relationship(
        back_populates="logo", sa_relationship_kwargs={"lazy": "selectin"}
    )
    image: Image = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
