import secrets
from datetime import datetime, timedelta, timezone

from itsdangerous import URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from app.models.user import User


def hash_password(password: str) -> str:
    return generate_password_hash(password, method="pbkdf2:sha256", salt_length=16)


def verify_password(user: User, password: str) -> bool:
    return check_password_hash(user.password_hash, password)


def make_reset_token(secret_key: str, email: str) -> str:
    serializer = URLSafeTimedSerializer(secret_key)
    return serializer.dumps(email, salt="password-reset")


def verify_reset_token(secret_key: str, token: str, max_age: int = 3600) -> str | None:
    serializer = URLSafeTimedSerializer(secret_key)
    try:
        return serializer.loads(token, salt="password-reset", max_age=max_age)
    except Exception:
        return None


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)
