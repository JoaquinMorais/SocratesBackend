from sqlmodel import Field, SQLModel


class Section(SQLModel, table=True):
    __tablename__ = "sections"

    id_section: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True, max_length=20)