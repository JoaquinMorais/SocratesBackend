from typing import Literal
from urllib.parse import urlsplit

from pydantic import ConfigDict, field_validator, model_validator
from sqlmodel import Field, SQLModel

from schemas.image import ImagePublic
from schemas.professor import ProfessorResponsiblePublic
from schemas.status import StatusPublic
from schemas.student_project import StudentProjectMemberPublic

Privacy = Literal["public", "private", "protected"]
MAX_GROUP_NUMBER = 9999


class ProjectCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")  # campos desconocidos -> 422

    id_section_year: int = Field(gt=0)
    group_number: int | None = Field(default=None, gt=0, le=MAX_GROUP_NUMBER)


class ProjectBulkCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    id_section_year: int = Field(gt=0)
    quantity: int = Field(ge=1, le=50)


def _validate_url(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"{field} must be an http(s) URL")
    return value


class ProjectUpdate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    objective: str | None = None
    problem: str | None = None
    drive_folder_url: str | None = Field(default=None, max_length=1000)
    user_link: str | None = Field(default=None, max_length=1000)
    privacy: Privacy | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("name cannot be blank")
        return v

    @field_validator("drive_folder_url")
    @classmethod
    def normalize_drive_folder(cls, v: str | None) -> str | None:
        return _validate_url(v, "drive_folder_url")

    @field_validator("user_link")
    @classmethod
    def normalize_user_link(cls, v: str | None) -> str | None:
        return _validate_url(v, "user_link")

    @model_validator(mode="after")
    def privacy_cannot_be_null(self):
        # `privacy` es obligatoria en el modelo: un null explícito es inválido
        # (a diferencia de los campos de texto, donde null limpia el valor).
        if "privacy" in self.model_fields_set and self.privacy is None:
            raise ValueError("privacy cannot be null")
        return self


class ProjectPublic(SQLModel):
    id_project: int
    id_section_year: int
    year: int
    id_section: int
    section_name: str
    group_number: int
    privacy: Privacy
    status: StatusPublic
    restricted: bool = False  # true: el detalle está oculto para este usuario
    name: str | None = None
    description: str | None = None
    objective: str | None = None
    problem: str | None = None
    drive_folder_url: str | None = None
    user_link: str | None = None
    logo: ImagePublic | None = None


class ProjectLogoUpdate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    id_image: int = Field(gt=0)


class ProjectList(SQLModel):
    items: list[ProjectPublic]
    total: int
    limit: int
    offset: int


class ProjectOverviewPublic(ProjectPublic):
    """Proyecto con sus integrantes y sus responsables (profesores del curso)."""

    members: list[StudentProjectMemberPublic]
    # Profesores asignados al curso lectivo, quienes hacen el seguimiento del grupo.
    responsible: list[ProfessorResponsiblePublic] = []
    # El jefe del grupo (`is_leader`), se resuelve aparte del filtro de estados.
    leader: StudentProjectMemberPublic | None = None