from sqlmodel import SQLModel


class LoginRequest(SQLModel):
    email: str
    password: str


class AccessToken(SQLModel):
    access_token: str
    token_type: str = "bearer"


class UserPublic(SQLModel):
    id_user: int
    first_name: str
    last_name: str
    file_number: int
    email: str
    role: str | None