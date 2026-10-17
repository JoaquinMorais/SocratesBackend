from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class Status(SQLModel, table=True):
    """Estado reutilizable por ámbito (`project`, `student_project`, ...)."""

    __tablename__ = "statuses"
    __table_args__ = (
        UniqueConstraint("ambito", "code", name="uq_status_ambito_code"),
    )

    id_status: int | None = Field(default=None, primary_key=True)
    ambito: str = Field(index=True, max_length=30)
    code: str = Field(max_length=30)
    name: str = Field(max_length=100)
    description: str | None = Field(default=None, max_length=200)
    is_final: bool = Field(default=False)
