import os
import hashlib
import base64
import logging
from datetime import datetime, timedelta, timezone

import jwt
import bcrypt
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# JWT Configuration from environment variables
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change_this_to_a_secure_secret_key_in_production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

_WEAK_DEFAULT = "change_this_to_a_secure_secret_key_in_production"


def validate_security_config():
    """Validate critical security configuration at application startup.

    Must be called before any background services start.
    In production (APP_ENV=production), raises RuntimeError if the JWT secret
    key is missing or matches the weak development default.
    In local development, logs a loud warning.
    """
    app_env = os.getenv("APP_ENV", "development").lower()
    is_production = app_env == "production"

    if not JWT_SECRET_KEY or JWT_SECRET_KEY == _WEAK_DEFAULT:
        msg = (
            "SECURITY: JWT_SECRET_KEY is unset or using the weak default value. "
            "Set a strong, unique JWT_SECRET_KEY in your .env file."
        )
        if is_production:
            raise RuntimeError(msg)
        logger.warning("=" * 60)
        logger.warning(msg)
        logger.warning("=" * 60)


def _prehash(plain_password: str) -> bytes:
    """SHA-256 pre-hash to eliminate bcrypt's 72-byte truncation limit.
    Returns the base64-encoded digest bytes.
    """
    digest = hashlib.sha256(plain_password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password using SHA-256 pre-hash + bcrypt."""
    prehashed = _prehash(plain_password)
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(prehashed, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against its bcrypt hash.
    Tries new SHA-256 pre-hashed format first, then falls back
    to legacy direct-bcrypt for backward compatibility.
    """
    hashed_bytes = hashed_password.encode("utf-8")
    # Try new pre-hashed format
    prehashed = _prehash(plain_password)
    if bcrypt.checkpw(prehashed, hashed_bytes):
        return True
    # Legacy fallback: direct bcrypt with 72-byte truncation
    legacy_bytes = plain_password.encode("utf-8")[:72]
    return bcrypt.checkpw(legacy_bytes, hashed_bytes)


def create_access_token(user_id: int, role: str) -> str:
    """Create a JWT access token with sub as the canonical user identifier.

    Claims:
        sub: str(user_id) - canonical subject claim
        user_id: int - extra metadata
        role: str - system access role (SUPERVISOR or ADMIN)
        exp: datetime - expiration timestamp
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "user_id": user_id,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token.

    Returns the decoded payload dict on success.
    Raises jwt.ExpiredSignatureError if the token has expired.
    Raises jwt.InvalidTokenError for any other validation failure.
    """
    return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
