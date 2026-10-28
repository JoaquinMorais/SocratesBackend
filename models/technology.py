from sqlalchemy import Index, text
from sqlmodel import Field, Relationship, SQLModel

from models.image import Image


class Technology(SQLModel, table=True):
    __tablename__ = "technologies"
    # Única sin distinguir mayúsculas: 'react' y 'React' son la misma tecnología.
    # La relación con la imagen es 1:1 (un id_image por tecnología, y una imagen
    # pertenece a una sola tecnología): así el borrado automático es seguro.
    __table_args__ = (
        Index("uq_technologies_name_lower", text("lower(name)"), unique=True),
    )

    id_technology: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    description: str | None = Field(default=None, max_length=500)
    id_image: int | None = Field(
        default=None, foreign_key="images.id_image", unique=True
    )

    image: Image | None = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
