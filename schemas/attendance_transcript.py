from typing import Literal

from pydantic import ConfigDict
from sqlmodel import Field, SQLModel

TranscriptFormat = Literal["text", "csv"]

TranscriptStatus = Literal[
    "would_create",
    "created",
    "already_present",
    "name_mismatch",
    "not_enrolled",
    "unknown_legajo",
    "invalid",
]


class AttendanceTranscriptText(SQLModel):
    """Texto pegado del chat (o un CSV pegado) para importar asistencia."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    format: TranscriptFormat = "text"


class TranscriptStudentPublic(SQLModel):
    id_student: int
    first_name: str
    last_name: str
    legajo: int


class TranscriptItemPublic(SQLModel):
    line: int
    occurrences: int = 1
    legajo: int | None = None
    written_name: str | None = None
    status: TranscriptStatus
    name_score: float | None = None
    student: TranscriptStudentPublic | None = None
    existing_method: str | None = None


class TranscriptSummaryPublic(SQLModel):
    lines: int
    ignored_lines: int
    attempts: int
    would_create: int
    created: int
    already_present: int
    name_mismatch: int
    not_enrolled: int
    unknown_legajo: int
    invalid: int


class AttendanceTranscriptReport(SQLModel):
    dry_run: bool
    file_name: str | None = None
    summary: TranscriptSummaryPublic
    items: list[TranscriptItemPublic] = Field(default_factory=list)
