"""
Environment configuration - loaded once, used everywhere
"""

import os
import secrets, string

DEBUG = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")
GIT_HASH = os.getenv("GIT_HASH", "dev")
APP_VERSION = os.getenv("APP_VERSION", "dev")
BUILD_TIMESTAMP = os.getenv("BUILD_TIMESTAMP", "unknown")
INIT_ADMIN_PASSWORD = str(os.getenv("INIT_ADMIN_PASSWORD", ""))

if not INIT_ADMIN_PASSWORD:
    chars = string.ascii_letters + string.digits + r"!@#\$%&*"
    INIT_ADMIN_PASSWORD = "".join(secrets.choice(chars) for _ in range(16))

MIN_PASSWORD_LENGTH = int(os.getenv("MIN_PASSWORD_LENGTH", 8))

# Load and validate Argon2 parameters
PASSWORD_HASHER_TIME_COST = int(os.getenv("PASSWORD_HASHER_TIME_COST", 2))
PASSWORD_HASHER_MEMORY_COST = int(os.getenv("PASSWORD_HASHER_MEMORY_COST", "65536"))
PASSWORD_HASHER_PARALLELISM = int(os.getenv("PASSWORD_HASHER_PARALLELISM", 4))

MAX_CONTENT_LENGTH = int(
    os.getenv("MAX_CONTENT_LENGTH", 20 * 1024 * 1024)
)  # 20MB default (videos bypass Flask via presigned PUT)

# Video upload feature flag and limits
VIDEO_UPLOADS_ENABLED = os.getenv("VIDEO_UPLOADS_ENABLED", "false").lower() in (
    "1", "true", "yes"
)
MAX_VIDEO_FILE_SIZE = int(os.getenv("MAX_VIDEO_FILE_SIZE", 200 * 1024 * 1024))  # 200MB
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm", "video/x-m4v"}
VIDEO_EXTENSIONS = {
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
    "video/x-m4v": "m4v",
}

# Background worker (Procrastinate on PostgreSQL), see worker.py
# Upper bound for one ffmpeg call of a video job; a hung process is killed and the job retried
VIDEO_JOB_TIMEOUT_SECONDS = int(os.getenv("VIDEO_JOB_TIMEOUT_SECONDS", "600"))

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
RATELIMIT_ENABLED = os.getenv("RATELIMIT_ENABLED", "true").lower() not in (
    "false",
    "0",
    "no",
)

# Redis (optional — enables Redis-backed sessions when set, falls back to filesystem)
REDIS_URL = os.getenv("REDIS_URL", None)
# Max cached watermark previews per library (scale/position combinations); oldest are evicted
WATERMARK_PREVIEW_CACHE_MAX_PER_LIBRARY = int(
    os.getenv("WATERMARK_PREVIEW_CACHE_MAX_PER_LIBRARY", "20")
)

# S3-compatible object storage (use Versity Gateway for local dev, Hetzner object storage in production)
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "http://s3:7070")
# Public URL used when generating presigned URLs — must be reachable by the browser
S3_PUBLIC_ENDPOINT_URL = os.getenv("S3_PUBLIC_ENDPOINT_URL", S3_ENDPOINT_URL)
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "").strip()
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "").strip()
S3_BUCKET = os.getenv("S3_BUCKET", "lumios")

# OpenTelemetry tracing: on when an OTLP endpoint is set (e.g. Jaeger), off otherwise
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "lumios-backend")
OTEL_SERVICE_VERSION = os.getenv("OTEL_SERVICE_VERSION", GIT_HASH)
OTEL_EXPORTER_ENDPOINT = os.getenv("OTEL_EXPORTER_ENDPOINT", "")

# Subscription tier limits — the only source of per-user quotas
SUBSCRIPTION_LIMITS = {
    "free": {
        "max_libraries": 1000,
        "max_images_per_library": 5000,
        "max_storage_bytes": 5 * 1024 * 1024 * 1024,  # 5 GB
    },
    "standard": {
        "max_libraries": 1000,
        "max_images_per_library": 5000,
        "max_storage_bytes": 200 * 1024 * 1024 * 1024,  # 200 GB
    },
    "premium": {
        "max_libraries": 1000,
        "max_images_per_library": 5000,
        "max_storage_bytes": 600 * 1024 * 1024 * 1024,  # 600 GB
    },
}

# Sentry error tracking (disabled while SENTRY_DSN is empty)
SENTRY_DSN = os.getenv("SENTRY_DSN", "")
SENTRY_ENVIRONMENT = os.getenv("SENTRY_ENVIRONMENT", "")
SENTRY_RELEASE = os.getenv("SENTRY_RELEASE", APP_VERSION)
SENTRY_TRACES_SAMPLE_RATE = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0"))

# Brevo transactional email
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
MAIL_SENDER_EMAIL = os.getenv("MAIL_SENDER_EMAIL", "lumios@niecke-it.de")
MAIL_SENDER_NAME = os.getenv("MAIL_SENDER_NAME", "Lumios")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")
# Brevo contact list ID for the waitlist (0 = not configured, only logs)
BREVO_WAITLIST_LIST_ID = int(os.getenv("BREVO_WAITLIST_LIST_ID", 0))

# Maximum number of active users allowed to register
MAX_USERS = int(os.getenv("MAX_USERS", 100))

# Failed password login protection: block an IP after this many failed attempts
# for the given number of minutes.
FAILED_LOGIN_MAX_ATTEMPTS = int(os.getenv("FAILED_LOGIN_MAX_ATTEMPTS", 5))
FAILED_LOGIN_BLOCK_MINUTES = int(os.getenv("FAILED_LOGIN_BLOCK_MINUTES", 15))
# Reverse proxies in front of the app that append to X-Forwarded-For; the client IP
# is the entry this many positions from the right.
TRUSTED_PROXY_COUNT = max(1, int(os.getenv("TRUSTED_PROXY_COUNT", 1)))

# Current AGB (Terms of Service) + AVV (Data Processing Agreement) version.
# Update this when publishing a new version of the legal documents.
CURRENT_AGB_VERSION = os.getenv("CURRENT_AGB_VERSION", "1.0")

# Origin of the landing page — allowed to make cross-origin requests to /api/v1/public/*
LANDINGPAGE_URL = os.getenv("LANDINGPAGE_URL", "https://lumios.niecke-it.de")

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
