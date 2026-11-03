from datetime import datetime, timedelta, timezone
import jwt
from pwdlib import PasswordHash
from app.core.config import settings

password_hash = PasswordHash.recommended()

def hash_password(password: str) -> str:
    return password_hash.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)

def create_token(subject: str, role: str, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": subject, "role": role, "type": token_type, "iat": now, "exp": now + expires_delta}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
