from sqlmodel import SQLModel


class LoginRequest(SQLModel):
    email: str
    password: str


class RefreshRequest(SQLModel):
    refresh_token: str


class TokenPair(SQLModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserPublic(SQLModel):
    id_user: int
    first_name: str
    last_name: str
    file_number: int
    email: str
    role: str | None