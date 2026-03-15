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
PASSWORD_HASHER_TIME_COST = int(os.getenv("PASSWORD_HASHER_TIME_COST", 2))
PASSWORD_HASHER_MEMORY_COST = int(os.getenv("PASSWORD_HASHER_MEMORY_COST", "65536"))
PASSWORD_HASHER_PARALLELISM = int(os.getenv("PASSWORD_HASHER_PARALLELISM", 4))

MAX_CONTENT_LENGTH = int(
    os.getenv("MAX_CONTENT_LENGTH", 20 * 1024 * 1024)
)  # 20MB default

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
    os.getenv("SQLALCHEMY_ENGINE_OPTIONS_POOL_SIZE", 3)
)
SQLALCHEMY_ENGINE_OPTIONS["max_overflow"] = int(
    os.getenv("SQLALCHEMY_ENGINE_OPTIONS_MAX_OVERFLOW", 3)
)

# Google OAuth (optional — Google login disabled when not set)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
# Separate OAuth client for the React frontend (GIS flow — no secret needed)
GOOGLE_FRONTEND_CLIENT_ID = os.getenv("GOOGLE_FRONTEND_CLIENT_ID")
# Must match the redirect URIs registered in Google Cloud Console exactly
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8080")
# URL of the frontend app — used to redirect back after OAuth callbacks
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

# App security
SECRET_KEY = os.getenv("SECRET_KEY")
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_EXPIRY_SECONDS = int(os.getenv("JWT_EXPIRY_SECONDS", 3600))

# Redis (optional — enables Redis-backed sessions when set, falls back to filesystem)
REDIS_URL = os.getenv("REDIS_URL", None)

# S3-compatible object storage (use MinIO for local dev, GCS/S3 in production)
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "http://minio:9000")
# Public URL used when generating presigned URLs — must be reachable by the browser
S3_PUBLIC_ENDPOINT_URL = os.getenv("S3_PUBLIC_ENDPOINT_URL", S3_ENDPOINT_URL)
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "").strip()
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "").strip()
S3_BUCKET = os.getenv("S3_BUCKET", "lumios")

# FAIL-FAST: Check required vars
REQUIRED_VARS = ["POSTGRES_PASSWORD", "SECRET_KEY", "JWT_SECRET"]
missing = [var for var in REQUIRED_VARS if not os.getenv(var)]
if missing:
    raise ValueError(
        f"Missing required environment variables: {', '.join(missing)}.\n"
        f"Add to .env:\n"
        f"  POSTGRES_PASSWORD=your_password\n"
        f"  SECRET_KEY=your-super-secret-key-at-least-32-chars\n"
        f"  JWT_SECRET=your-super-jwt-secret-change-me"
    )

if SECRET_KEY and len(SECRET_KEY) < 32:
    raise ValueError("SECRET_KEY must be at least 32 characters")
if JWT_SECRET and len(JWT_SECRET) < 32:
    raise ValueError("JWT_SECRET must be at least 32 characters")
