from sqlalchemy import Index, text
from sqlmodel import Field, SQLModel


class Section(SQLModel, table=True):
    __tablename__ = "sections"
    __table_args__ = (
        Index(
            "uq_sections_generic",
            "is_generic",
            unique=True,
            postgresql_where=text("is_generic"),
        ),
    )

    id_section: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True, max_length=20)
    is_generic: bool = Field(default=False)