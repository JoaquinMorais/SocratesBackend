from sqlmodel import Field, Relationship, SQLModel

from models.project import Project
from models.technology import Technology


class ProjectTechnology(SQLModel, table=True):
    __tablename__ = "project_technologies"
    # Clave compuesta a propósito: el par proyecto-tecnología solo existe una vez.

    id_project: int = Field(foreign_key="projects.id_project", primary_key=True, ondelete="CASCADE")
    id_technology: int = Field(
        foreign_key="technologies.id_technology", primary_key=True, ondelete="RESTRICT"
    )

    project: Project = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
    technology: Technology = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
