from datetime import date as date_type
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import ConfigDict, field_validator
from sqlmodel import Field, SQLModel

from schemas.activity import ActivityPublic
from schemas.status import StatusPublic


def _validate_link(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("link must be an http(s) URL")
    return value


class DeliveryUpdate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    link: str | None = Field(default=None, max_length=1000)

    @field_validator("link")
    @classmethod
    def normalize_link(cls, value: str | None) -> str | None:
        return _validate_link(value)


class DeliveryRepairCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    id_activity: int = Field(gt=0)
    link: str | None = Field(default=None, max_length=1000)

    @field_validator("link")
    @classmethod
    def normalize_link(cls, value: str | None) -> str | None:
        return _validate_link(value)


GradeCategory = Literal["follow_up", "activity"]


class DeliveryGradeCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    category: GradeCategory
    id_score: int = Field(gt=0)


class DeliveryGradeUpdate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    category: GradeCategory | None = None
    id_score: int | None = Field(default=None, gt=0)


class DeliveryScorePublic(SQLModel):
    id_score: int
    code: str
    name: str
    value: int


class DeliveryGradePublic(SQLModel):
    id_delivery_grade: int
    id_delivery: int
    category: GradeCategory
    score: DeliveryScorePublic
    graded_at: datetime


class DeliveryGradeList(SQLModel):
    items: list[DeliveryGradePublic]


class DeliveryProjectSummary(SQLModel):
    id_project: int
    group_number: int
    name: str | None = None


class DeliveryPublic(SQLModel):
    id_delivery: int
    id_project: int
    id_activity: int
    id_section_year: int
    activity: ActivityPublic
    project: DeliveryProjectSummary
    status: StatusPublic
    link: str | None = None
    submitted_at: datetime | None = None
    updated_at: datetime | None = None
    grades: list[DeliveryGradePublic] = []
    latest_grades: list[DeliveryGradePublic] = []


class DeliveryList(SQLModel):
    items: list[DeliveryPublic]
    total: int
    limit: int
    offset: int
