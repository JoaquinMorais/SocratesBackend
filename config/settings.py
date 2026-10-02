from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_MINUTES: int = 15
    REFRESH_DAYS: int = 7
    OTP_MINUTES: int = 10
    EMAIL_DOMAIN: str = "sistemas.frc.utn.edu.ar"
    
    COOKIE_SECURE: bool = False  # True en producción (HTTPS)
    COOKIE_SAMESITE: str = "lax"


    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()