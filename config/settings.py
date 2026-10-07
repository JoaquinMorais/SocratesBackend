from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_MINUTES: int = 15
    REFRESH_DAYS: int = 7
    COOKIE_SECURE: bool = False  # True en producción (HTTPS)
    COOKIE_SAMESITE: str = "lax"

    OTP_MINUTES: int = 10
    OTP_COOLDOWN_SECONDS: int = 60
    OTP_MAX_ATTEMPTS: int = 5
    EMAIL_DOMAIN: str = "sistemas.frc.utn.edu.ar"

    EMAIL_BACKEND: str = "console"  # "console" | "smtp"
    EMAIL: str = ""
    EMAIL_PASSWORD: str = ""
    EMAIL_FROM: str = ""
    EMAIL_DEV_REDIRECT: str = ""  # si tiene valor, todos los mails van ahí
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_TIMEOUT: int = 10

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()