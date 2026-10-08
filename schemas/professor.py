import re
from datetime import date

from pydantic import field_validator
from sqlmodel import Field, SQLModel

from config.settings import settings

_MAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ProfessorCreate(SQLModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    legajo: int = Field(gt=0)
    birth_date: date
    mail: str = Field(max_length=255)
    is_super_admin: bool = False

    @field_validator("mail")
    @classmethod
    def validate_mail(cls, v: str) -> str:
        v = v.strip().lower()
        if not _MAIL_RE.match(v):
            raise ValueError("Invalid mail")
        if v.endswith(f"@{settings.EMAIL_DOMAIN}"):
            raise ValueError(f"@{settings.EMAIL_DOMAIN} is reserved for students")
        return v


class ProfessorPublic(SQLModel):
    id_professor: int
    first_name: str
    last_name: str
    legajo: int
    email: str
    is_super_admin: bool