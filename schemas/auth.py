from sqlmodel import Field, SQLModel


class LoginRequest(SQLModel):
    email: str
    password: str


class AccessToken(SQLModel):
    access_token: str
    token_type: str = "bearer"


class PasswordRequest(SQLModel):
    email: str


class PasswordConfirm(SQLModel):
    email: str
    code: str
    new_password: str = Field(min_length=8, max_length=128)