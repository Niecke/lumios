"""
Environment configuration - loaded once, used everywhere
"""

import os
import secrets, string

DEBUG = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")
INIT_ADMIN_PASSWORD = str(os.getenv("INIT_ADMIN_PASSWORD", ""))
INIT_ADMIN_LENGTH = int(os.getenv("INIT_ADMIN_LENGTH", 16))
INIT_ADMIN_SPECIAL_CHARS = str(os.getenv("INIT_ADMIN_SPECIAL_CHARS", r"!@#\$%&*"))

if not INIT_ADMIN_PASSWORD:
    chars = string.ascii_letters + string.digits + INIT_ADMIN_SPECIAL_CHARS
    INIT_ADMIN_PASSWORD = "".join(
        secrets.choice(chars) for _ in range(INIT_ADMIN_LENGTH)
    )

MIN_PASSWORD_LENGTH = int(os.getenv("MIN_PASSWORD_LENGTH", 8))

# Load and validate Argon2 parameters
PASSWORD_HASHER_TIME_COST = int(os.getenv("PASSWORD_HASHER_TIME_COST", "2"))
PASSWORD_HASHER_MEMORY_COST = int(os.getenv("PASSWORD_HASHER_MEMORY_COST", "65536"))
PASSWORD_HASHER_PARALLELISM = int(os.getenv("PASSWORD_HASHER_PARALLELISM", "4"))

# Database
POSTGRES_USER = str(os.getenv("POSTGRES_USER", "lumios"))
POSTGRES_PASSWORD = str(os.getenv("POSTGRES_PASSWORD"))
POSTGRES_HOST = str(os.getenv("POSTGRES_HOST", "postgres"))
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", 5432))
POSTGRES_DB = str(os.getenv("POSTGRES_DB", "lumios"))

SQLALCHEMY_TRACK_MODIFICATIONS = os.getenv(
    "SQLALCHEMY_TRACK_MODIFICATIONS", "false"
).lower() in ("1", "true", "yes")

SQLALCHEMY_ENGINE_OPTIONS = dict()
SQLALCHEMY_ENGINE_OPTIONS["pool_pre_ping"] = bool(
    os.getenv("SQLALCHEMY_ENGINE_OPTIONS_POOL_PRE_PING", True)
)
SQLALCHEMY_ENGINE_OPTIONS["pool_recycle"] = int(
    os.getenv("SQLALCHEMY_ENGINE_OPTIONS_POOL_RECYCLE", 3600)
)
SQLALCHEMY_ENGINE_OPTIONS["pool_timeout"] = int(
    os.getenv("SQLALCHEMY_ENGINE_OPTIONS_POOL_TIMEOUT", 30)
)
SQLALCHEMY_ENGINE_OPTIONS["pool_size"] = int(
    os.getenv("SQLALCHEMY_ENGINE_OPTIONS_POOL_SIZE", 5)
)
SQLALCHEMY_ENGINE_OPTIONS["max_overflow"] = int(
    os.getenv("SQLALCHEMY_ENGINE_OPTIONS_MAX_OVERFLOW", 10)
)

# Google OAuth (optional — Google login disabled when not set)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

# App security
SECRET_KEY = os.getenv("SECRET_KEY")

# Redis (optional — enables Redis-backed sessions when set, falls back to filesystem)
REDIS_URL = os.getenv("REDIS_URL", None)

# FAIL-FAST: Check required vars
REQUIRED_VARS = ["POSTGRES_PASSWORD", "SECRET_KEY"]
missing = [var for var in REQUIRED_VARS if not os.getenv(var)]
if missing:
    raise ValueError(
        f"Missing required environment variables: {', '.join(missing)}.\n"
        f"Add to .env:\n"
        f"  POSTGRES_PASSWORD=your_password\n"
        f"  SECRET_KEY=your-super-secret-key-at-least-32-chars"
    )
