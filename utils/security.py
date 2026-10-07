import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from jose import JWTError, jwt

from config.settings import settings

_ph = PasswordHasher()


# --- contraseñas ---
def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


# --- refresh token (opaco) ---
def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# --- OTP del mail ---
def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(code: str) -> str:
    # HMAC con la SECRET_KEY: un código de 6 dígitos con SHA-256 simple
    # se rompe por fuerza bruta si se filtra la BD
    return hmac.new(settings.SECRET_KEY.encode(), code.encode(), hashlib.sha256).hexdigest()


# --- access token (JWT) ---
def create_access_token(id_user: int, legajo: int) -> str:
    payload = {
        "sub": str(id_user),
        "legajo": legajo,
        "type": "access",
        "jti": uuid.uuid4().hex,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None
    return payload if payload.get("type") == "access" else None