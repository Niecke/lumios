import jwt
from datetime import datetime, timezone, timedelta
from config import JWT_SECRET, JWT_EXPIRY_SECONDS


def create_token(user_id: int, email: str, roles: list[str]) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "roles": roles,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(seconds=JWT_EXPIRY_SECONDS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> dict:
    """Returns the payload or raises jwt.PyJWTError on invalid/expired token."""
    return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
