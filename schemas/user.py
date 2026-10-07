from sqlmodel import SQLModel


class UserPublic(SQLModel):
    id_user: int
    first_name: str
    last_name: str
    legajo: int
    email: str
    role: str | None
    is_super_admin: bool = False