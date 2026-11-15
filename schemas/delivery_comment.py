from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, field_validator
from sqlmodel import Field, SQLModel

from schemas.activity import ActivityPublic
from schemas.delivery import DeliveryProjectSummary
from schemas.professor import ProfessorResponsiblePublic
from schemas.status import StatusPublic

CommentKind = Literal["feedback", "annotation"]
MAX_COMMENT_LENGTH = 2000


def _clean_content(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("content cannot be blank")
    return value


class DeliveryCommentCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    kind: CommentKind = "feedback"
    content: str = Field(min_length=1, max_length=MAX_COMMENT_LENGTH)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        return _clean_content(value)


class DeliveryCommentUpdate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    content: str | None = Field(
        default=None, min_length=1, max_length=MAX_COMMENT_LENGTH
    )

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str | None) -> str | None:
        return None if value is None else _clean_content(value)


class DeliveryCommentPublic(SQLModel):
    id_delivery_comment: int
    id_delivery: int
    id_project: int
    id_activity: int
    id_section_year: int
    kind: CommentKind
    author: ProfessorResponsiblePublic
    project: DeliveryProjectSummary
    activity: ActivityPublic
    content: str
    status: StatusPublic
    created_at: datetime
    updated_at: datetime
    corrected_at: datetime | None = None


class DeliveryCommentList(SQLModel):
    items: list[DeliveryCommentPublic]
    total: int
    limit: int
    offset: int
