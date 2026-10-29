from pydantic_settings import BaseSettings, SettingsConfigDict


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

    SEND_WELCOME_EMAILS: bool = True

    # Imágenes: por ahora solo en disco local (MEDIA_DIR); la URL pública que
    # devuelve la API se arma con MEDIA_BASE_URL + key.
    MEDIA_DIR: str = "media"
    MEDIA_BASE_URL: str = "http://localhost:8000/media"
    IMAGE_MAX_BYTES: int = 5_000_000  # 5 MB por archivo
    IMAGE_WEBP_QUALITY: int = 85  # calidad de la conversión a WebP

    # Asistencia: minutos que vale el código de una clase.
    ATTENDANCE_CODE_MINUTES: int = 10
    # Asistencia desde el chat: tamaño máximo del texto y tolerancia del nombre.
    ATTENDANCE_TRANSCRIPT_MAX_BYTES: int = 2_000_000
    ATTENDANCE_NAME_SIMILARITY: float = 0.75


    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    '''
    class Config:
        env_file = ".env"
        extra = "ignore"
    '''


settings = Settings()