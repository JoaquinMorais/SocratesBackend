from sqlmodel import Field, SQLModel

from schemas.project import ProjectOverviewPublic
from schemas.student import StudentGroupPublic


class MyProjectPublic(SQLModel):
    """Respuesta de `GET /me/project`: mi equipo (o `null`) y mis solicitudes."""

    project: ProjectOverviewPublic | None = None
    requests: list[StudentGroupPublic] = Field(default_factory=list)
