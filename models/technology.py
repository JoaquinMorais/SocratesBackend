from sqlalchemy import Index, text
from sqlmodel import Field, SQLModel


class Technology(SQLModel, table=True):
    __tablename__ = "technologies"
    # Única sin distinguir mayúsculas: 'react' y 'React' son la misma tecnología.
    __table_args__ = (
        Index("uq_technologies_name_lower", text("lower(name)"), unique=True),
    )

    id_technology: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    description: str | None = Field(default=None, max_length=500)
