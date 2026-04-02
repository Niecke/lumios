# Lumios — Claude Code Guide

Photo library platform for professional photographers. Photographers upload libraries and share them with customers via unique links. Customers view watermarked previews and mark favourites. Photographer is notified when a customer completes their selection.

Domain: **lumios.niecke-it.de** (landing page), **lumios-app.niecke-it.de** (app) | Open source

---

## Stack

| Layer | Technology |
|---|---|
| Backend API | Python 3.13, Flask 3.x, Gunicorn, Distroless container |
| Admin UI | Flask + Jinja2 templates, integrated in backend under `/admin` |
| Frontend SPA | React 19, TanStack Query, TanStack Router (file-based), Vite 8, TypeScript |
| Landing page | Separate static site, deployed as its own Cloud Run service |
| Database | PostgreSQL 18 (Podman container on e2-small VM) |
| Cache / Sessions | Redis 8 (Podman container on same e2-small VM) |
| File storage | S3-compatible (MinIO for local dev, GCS HMAC in production) via boto3 |
| Image processing | Pillow — inline in Flask, no separate worker |
| Auth | Google OAuth 2.0 (photographers + admins); JWT tokens for API; UUID share links (customers) |
| Email | Brevo (formerly Sendinblue) transactional API |
| Observability | OpenTelemetry → Cloud Trace (prod) / Jaeger (local dev) |
| CDN / SSL / Domain | Cloudflare free plan (proxy, SSL termination, edge caching) |
| IaC | Terraform + GitHub Actions |
| Local dev | Podman + podman-compose |

---

## Repository Layout

```
lumios/
├── backend/                  # Flask application (start here)
│   ├── app/
│   │   ├── blueprints/
│   │   │   ├── admin.py      # /admin — Jinja2 UI, admin role required
│   │   │   ├── auth.py       # /auth — Google OAuth, login, logout (session-based)
│   │   │   ├── health.py     # /health endpoint for monitoring
│   │   │   └── api/          # JSON API (JWT-authenticated)
│   │   │       ├── __init__.py       # Parent blueprint, url_prefix=/api/v1
│   │   │       ├── auth.py           # /api/v1/auth — JWT login, register, OAuth
│   │   │       ├── libraries.py      # /api/v1/libraries — CRUD, watermark mgmt
│   │   │       ├── images.py         # /api/v1/libraries/<id>/images — upload, delete
│   │   │       ├── public.py         # /api/v1/public — share links, waitlist, registration status
│   │   │       ├── notifications.py  # /api/v1/notifications — user notifications
│   │   │       ├── support.py        # /api/v1/support — support tickets
│   │   │       └── feedback.py       # /api/v1/feedback — user feedback/ratings
│   │   ├── services/
│   │   │   ├── audit.py      # Audit log creation helpers
│   │   │   ├── auth.py       # Auth service logic
│   │   │   ├── mail.py       # Brevo email sending
│   │   │   ├── storage.py    # S3-compatible storage operations
│   │   │   └── token.py      # JWT token generation/validation
│   │   ├── migrations/       # Alembic migration files
│   │   ├── static/
│   │   ├── templates/
│   │   ├── tests/
│   │   ├── commands.py       # CLI commands: purge_deleted_accounts, purge_audit_logs, apply_agb_acceptance
│   │   ├── config.py         # All env vars loaded here — fail-fast on missing
│   │   ├── current_user.py   # Thread-local current user helper
│   │   ├── log.py            # Structured JSON logging
│   │   ├── main.py           # App factory: create_app()
│   │   ├── models.py         # SQLAlchemy models
│   │   ├── password_handler.py # Argon2id config
│   │   ├── security.py       # @login_required, @require_role, @require_api_auth, @require_api_role
│   │   ├── tracing.py        # @traced decorator for OpenTelemetry spans
│   │   └── gunicorn_logging.conf
│   ├── Dockerfile            # Multi-stage: builder + distroless runtime
│   ├── entrypoint.py         # Waits for DB, runs flask db upgrade, starts Gunicorn
│   └── requirements.txt
├── frontend/                 # React SPA (TanStack Router file-based routing)
│   ├── src/
│   │   ├── api/              # API client modules (auth, images, libraries, etc.)
│   │   ├── components/       # AppBar, CookieBanner, FeedbackWidget
│   │   ├── routes/           # File-based routes (TanStack Router)
│   │   └── main.tsx
│   ├── Dockerfile
│   ├── nginx.conf.template
│   └── package.json
├── landingpage/              # Static landing page (separate Cloud Run service)
├── terraform/                # All GCP infrastructure
│   ├── environments/prod/    # Production environment (main.tf, variables.tf, backend.tf)
│   └── modules/              # apis, network, storage, secrets, vm, artifact_registry, cloudrun, cleanup, monitoring
├── .github/workflows/        # CI/CD pipelines
├── docker-compose.yml        # Local dev: backend, frontend, landingpage, postgres, redis, minio, jaeger
├── CLAUDE.md                 # This file
└── TODO.md                   # Contains the next steps
```

---

## Commands

```bash
# Local development
podman-compose up                        # Start all services
podman-compose up --build                # Rebuild after dependency changes

# Backend migrations (requires running services — run from lumios/)
# Always ensure services are up before generating or applying migrations:
podman-compose up -d --build --force-recreate
podman exec -e FLASK_APP="main:create_app()" lumios-backend /usr/bin/python3 -m flask db migrate -m "description"
podman exec -e FLASK_APP="main:create_app()" lumios-backend /usr/bin/python3 -m flask db upgrade

# Backend tests (run from backend/app/ — uses SQLite in-memory, no services needed)
# only for test setup
python3 -m venv ./.venv
source ./.venv/bin/activate
./.venv/bin/pip install -r ./backend/requirements.txt
./.venv/bin/pip install -r ./backend/requirements-test.txt
# for each test run
source ./.venv/bin/activate
python -m pytest ./backend/app/tests/ -v

# CLI commands (registered in main.py)
flask purge-deleted-accounts             # Hard-delete accounts soft-deleted > 1 year
flask purge-audit-logs                   # Purge audit logs older than 90 days
flask apply-agb-acceptance               # Apply AGB acceptance after effective date

# Docker image (CI pattern)
docker build --build-arg GIT_SHA=$(git rev-parse --short HEAD) -t lumios-backend .
```

---

## Environment Variables

Defined and validated in `backend/app/config.py`. The app **refuses to start** if required vars are missing.

### Required
| Variable | Description |
|---|---|
| `SECRET_KEY` | Flask secret key, min 32 chars |
| `POSTGRES_PASSWORD` | PostgreSQL password |
| `JWT_SECRET` | JWT signing secret, min 32 chars |

### Optional (with defaults)
| Variable | Default | Description |
|---|---|---|
| `POSTGRES_USER` | `lumios` | DB user |
| `POSTGRES_HOST` | `postgres` | DB host |
| `POSTGRES_PORT` | `5432` | DB port |
| `POSTGRES_DB` | `lumios` | DB name |
| `REDIS_URL` | `None` | Falls back to filesystem sessions if unset |
| `DEBUG` | `false` | Enables hot-reload, disables HTTPS enforcement |
| `GIT_HASH` | `dev` | Injected at Docker build time |
| `GOOGLE_CLIENT_ID` | — | Google OAuth client ID (backend / Jinja2 login) |
| `GOOGLE_CLIENT_SECRET` | — | Google OAuth client secret |
| `GOOGLE_FRONTEND_CLIENT_ID` | — | Separate OAuth client for React frontend (GIS flow) |
| `PUBLIC_BASE_URL` | `http://localhost:8080` | Must match OAuth redirect URIs |
| `FRONTEND_URL` | `http://localhost:5173` | URL of the React frontend |
| `JWT_EXPIRY_SECONDS` | `3600` | JWT token lifetime |
| `S3_ENDPOINT_URL` | `http://minio:9000` | S3-compatible endpoint (MinIO locally, GCS in prod) |
| `S3_PUBLIC_ENDPOINT_URL` | same as above | Public URL for presigned URLs (must be browser-reachable) |
| `S3_ACCESS_KEY` | — | S3/HMAC access key |
| `S3_SECRET_KEY` | — | S3/HMAC secret key |
| `S3_BUCKET` | `lumios` | Bucket name |
| `CLOUD_TRACE_ENABLED` | `false` | Enable OpenTelemetry tracing |
| `GOOGLE_CLOUD_PROJECT` | — | GCP project ID for Cloud Trace |
| `OTEL_EXPORTER_ENDPOINT` | — | OTLP endpoint (e.g. Jaeger); overrides Cloud Trace |
| `BREVO_API_KEY` | — | Brevo transactional email API key |
| `MAIL_SENDER_EMAIL` | `lumios@niecke-it.de` | Sender email address |
| `MAIL_SENDER_NAME` | `Lumios` | Sender display name |
| `ADMIN_EMAIL` | — | Admin notification email |
| `BREVO_WAITLIST_LIST_ID` | `0` | Brevo contact list for waitlist (0 = disabled) |
| `MAX_USERS` | `100` | Max active users allowed to register |
| `CURRENT_AGB_VERSION` | `1.0` | Current Terms of Service version |
| `LANDINGPAGE_URL` | `https://lumios.niecke-it.de` | Landing page origin (CORS allowlist) |
| `MAX_CONTENT_LENGTH` | `20MB` | Max upload size |

Never commit `.env`. Never bake secrets into the Docker image.

---

## Database Schema

All models in `backend/app/models.py`. Migrations in `backend/app/migrations/versions/`.

```python
# Key relationships
User          --< roles_users >-- Role          # many-to-many
User (photographer) --< Library                 # one-to-many
Library             --< Image                   # one-to-many
User                --< SupportTicket           # one-to-many
SupportTicket       --< SupportTicketComment    # one-to-many
User                --< Notification            # one-to-many
User                --< Feedback                # one-to-many
User                --> AuditLog                # append-only
```

### Enums

- `SubscriptionType`: `free`, `standard`, `premium`
- `CustomerState`: `none`, `liked`
- `NotificationType`: `library_marked`, `library_viewed`, `ticket_comment_added`
- `SupportTicketStatus`: `open`, `closed`
- `AuditLogType`: `user_created`, `user_activated`, `user_deactivated`, `user_reactivated`, `user_deleted`, `password_changed`, `password_set_by_admin`, `login_backend`, `login_frontend`, `login_failed`, `library_created`, `library_edited`, `library_deleted`, `library_finished`, `picture_uploaded`, `picture_deleted`, `picture_downloaded`, `gdpr_export`

### Tables

**users** — `id, email, active, activation_pending, activation_token, account_type ('local' | 'google'), auth_string, max_libraries (default 100), max_images_per_library (default 500), created_at, last_login, deleted_at, agb_accepted_at, agb_version, is_system, subscription (SubscriptionType, default free)`

`account_type` determines how the user authenticates:
- `'local'` — `auth_string` holds an Argon2id-hashed password. Used only for the seeded admin account.
- `'google'` — `auth_string` holds the Google `sub` (subject identifier). Set on first successful OAuth callback.

Subscription tier limits (defined in `config.py`) set caps; per-user `max_*` columns allow stricter limits (lower wins). See `User.effective_limits`.

**roles** — `id, name ('admin' | 'photographer'), description`

**roles_users** — `user_id FK, role_id FK` (junction table, indexed on both columns)

**libraries** — `id, uuid (unique, indexed), user_id FK, name, created_at, archived_at, deleted_at, finished_at, use_original_as_preview, download_enabled, is_private, last_viewed_at, watermark_gcs_key, watermark_scale, watermark_position`

**images** — `id, uuid (unique, indexed), library_id FK, s3_key, original_filename, content_type, size, width, height, customer_state (CustomerState, default none), created_at, deleted_at`

`Image.storage_path(variant)` builds the full S3 key: `photos/{photographer_id}/{library_id}/{variant}/{uuid}.{ext}` where variant is `originals`, `previews`, or `thumbs`.

**support_tickets** — `id, user_id FK, subject, body, status (SupportTicketStatus, default open), created_at, updated_at`

**support_ticket_comments** — `id, ticket_id FK, body, created_at`

**notifications** — `id, created_at, seen_at, type (NotificationType), user_id FK, related_object`

**waitlist** — `id, email (unique), created_at`

**audit_logs** — `id (UUIDBinary), audit_type (AuditLogType), ip_address, audit_date (indexed), creator_id FK, related_object_type, related_object_id`

**job_runs** — `id, job_name (indexed), ran_at, status, records_affected, error_message`

**feedbacks** — `id, user_id FK, rating, body, admin_note, created_at, updated_at`

**agb_updates** — `id, version, summary, notified_at (indexed), effective_at, applied_at`

### Rules
- `deleted_at` is set when a user/library/image is soft-deleted. Hard delete runs after 1 year via `flask purge-deleted-accounts`.
- `archived_at` is set by lifecycle job after 1 year. GCS lifecycle rule moves object to Nearline storage.
- Audit logs retain for 90 days then are purged via `flask purge-audit-logs` (IP address is personal data under GDPR).

---

## Flask App Patterns

Follow the existing codebase conventions precisely:

```python
# Blueprint registration in main.py create_app()
# Template-based routes (session auth):
from blueprints.auth import auth
app.register_blueprint(auth)

# API routes (JWT auth, nested under /api/v1):
from blueprints.api import api
app.register_blueprint(api)
# Sub-blueprints are registered inside blueprints/api/__init__.py

# Route protection — template routes (session-based)
from security import login_required, require_role

@admin.route('/admin/dashboard')
@login_required
@require_role('admin')
def dashboard():
    ...

# Route protection — API routes (JWT-based)
from security import require_api_auth, require_api_role

@libraries_api.route("", methods=["GET"])
@require_api_auth
@require_api_role("photographer")
def list_libraries():
    ...

# DB queries — always use SQLAlchemy 2.x style
from sqlalchemy import select
users = db.session.execute(select(User).where(User.active == True)).scalars().all()

# Audit logging — use the audit service
from services.audit import create_audit_log

# Rate limiting — use existing limiter from main.py
from main import limiter

@auth.route('/login', methods=['POST'])
@limiter.limit("2 per second")
def login():
    ...
```

### Security constraints (never skip these)
- Template routes are CSRF-protected via flask-wtf; API blueprints are CSRF-exempt (JWT-authenticated)
- Sessions are server-side in Redis (`SESSION_COOKIE_HTTPONLY=True`, `SAMESITE=Lax`)
- Argon2id for all password hashing via `password_handler.py` — never use any other hash
- flask-talisman enforces HTTPS and CSP in production (`DEBUG=false`)
- Rate limiter is always active — do not bypass it in production code
- CORS is configured to allow only the landing page origin (`LANDINGPAGE_URL`) on `/api/v1/public/*`

---

## S3 File Handling

```python
# S3 key structure (built by Image.storage_path())
f"photos/{photographer_id}/{library_id}/originals/{uuid}.{ext}"
f"photos/{photographer_id}/{library_id}/previews/{uuid}.{ext}"   # watermarked
f"photos/{photographer_id}/{library_id}/thumbs/{uuid}.{ext}"     # 300px

# Access rules
# - Originals: NEVER served to customers, no signed URLs issued
# - Previews + thumbnails: presigned URLs via storage service
# - Uploads: Flask receives multipart, validates, then streams to S3
```

### Upload validation
1. MIME type must be `image/jpeg` or `image/png` — reject everything else
2. Library must have fewer than `max_images_per_library` images (respects subscription tier)
3. Photographer must own the library

### Thumbnail generation (inline, no queue)
1. Validate MIME type and library capacity
2. Generate watermarked preview with Pillow (custom watermark image per library, or centred text overlay)
3. Generate 300px thumbnail with Pillow
4. Upload all three variants to S3
5. Insert image metadata to DB
6. Return image metadata in response

---

## Share Link Mechanism

```
URL: https://lumios-app.niecke-it.de/library/<uuid>
- No authentication required
- Backend validates UUID exists and library is active
- Writes audit_log entry on access
- Returns image metadata list (preview URLs and thumb URLs only — never original)
```

---

## API Endpoints

```
GET  /health                                        # DB ping, returns {status, database, git_hash}

# Auth (template-based, session)
GET  /login                                         # Login page
POST /login                                         # Session login
GET  /auth/google                                   # Redirect to Google OAuth
GET  /auth/callback                                 # OAuth callback, sets session
POST /logout                                        # Clear session

# API Auth (/api/v1/auth, JWT)
GET  /api/v1/auth/me                                # Current user info
POST /api/v1/auth/login                             # JWT login (email/password)
POST /api/v1/auth/google/verify                     # Verify Google ID token
POST /api/v1/auth/google/callback                   # Google OAuth code exchange
POST /api/v1/auth/exchange                          # Exchange session for JWT
POST /api/v1/auth/register                          # Register new account
POST /api/v1/auth/google/register                   # Register via Google
POST /api/v1/auth/activate                          # Activate account with token
POST /api/v1/auth/change_password                   # Change password

# Libraries (/api/v1/libraries, JWT, photographer role)
GET  /api/v1/libraries                              # List photographer's libraries
POST /api/v1/libraries                              # Create library {name}
GET  /api/v1/libraries/uuid/<uuid>                  # Library detail by UUID
PATCH /api/v1/libraries/<id>                        # Update library settings
DELETE /api/v1/libraries/<id>                        # Soft-delete library
POST /api/v1/libraries/<id>/watermark               # Upload custom watermark
DELETE /api/v1/libraries/<id>/watermark              # Remove watermark
GET  /api/v1/libraries/<id>/watermark/preview        # Preview watermark on sample image

# Images (/api/v1/libraries/<id>/images, JWT, photographer role)
GET  /api/v1/libraries/<id>/images                  # List images in library
POST /api/v1/libraries/<id>/images                  # Upload image (multipart)
DELETE /api/v1/libraries/<id>/images/<image_id>      # Delete image

# Public (/api/v1/public, no auth)
GET  /api/v1/public/libraries/<uuid>                # Get library + image metadata (share link)
POST /api/v1/public/libraries/<uuid>/images/<id>/toggle  # Toggle favourite
POST /api/v1/public/libraries/<uuid>/finish          # Mark selection complete
GET  /api/v1/public/libraries/<uuid>/images/<id>/download  # Download original (if enabled)
GET  /api/v1/public/registration_status              # Check if registration is open
POST /api/v1/public/waitlist                         # Join waitlist
POST /api/v1/public/client-errors                    # Report frontend errors

# Notifications (/api/v1/notifications, JWT)
GET  /api/v1/notifications                          # List notifications (paginated)
PATCH /api/v1/notifications/<id>/seen               # Mark notification as seen

# Support (/api/v1/support, JWT)
GET  /api/v1/support/tickets                        # List user's tickets
POST /api/v1/support/tickets                        # Create support ticket
GET  /api/v1/support/tickets/<id>                   # Get ticket with comments

# Feedback (/api/v1/feedback, JWT)
POST /api/v1/feedback                               # Submit feedback (rating + body)

# Admin (admin role required, Jinja2-rendered)
GET  /admin/dashboard
GET  /admin/users
GET/POST /admin/user_create
GET/POST /admin/user_edit/<id>
GET/POST /change_password
GET/POST /admin/set_password/<id>
POST /admin/user_delete/<id>
POST /admin/user_gdpr_export/<user_id>
GET  /admin/support
GET  /admin/support/<ticket_id>
POST /admin/support/<ticket_id>/comment
POST /admin/support/<ticket_id>/close
GET  /admin/feedback
POST /admin/feedback/<feedback_id>/note
GET/POST /admin/notify_agb
GET  /admin/auditlogs
```

---

## Testing Conventions

Tests use SQLite in-memory — no external services required. Follow `tests/conftest.py` exactly:

```python
# Always set env vars before any app import
os.environ.setdefault("POSTGRES_PASSWORD", "test_password")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars-long!")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-key-at-least-32-chars-long!")
os.environ.setdefault("DEBUG", "true")  # disables Talisman HTTPS enforcement

# Use minimal Argon2 params — hashing is slow otherwise
os.environ.setdefault("PASSWORD_HASHER_TIME_COST", "1")
os.environ.setdefault("PASSWORD_HASHER_MEMORY_COST", "8")
os.environ.setdefault("PASSWORD_HASHER_PARALLELISM", "1")

# SQLite replaces PostgreSQL in tests
test_config = {
    "TESTING": True,
    "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    "SQLALCHEMY_ENGINE_OPTIONS": {
        "connect_args": {"check_same_thread": False},
        "poolclass": StaticPool,
    },
    "WTF_CSRF_ENABLED": False,
    "RATELIMIT_ENABLED": False,
    "SESSION_TYPE": "filesystem",
    "SESSION_FILE_DIR": "/tmp/flask_test_sessions",
}
```

### Test files
```
tests/
├── conftest.py               # Fixtures: app, client, admin_user, regular_user, inactive_user
├── test_admin.py
├── test_api_auth.py
├── test_api_images.py
├── test_api_libraries.py
├── test_api_public.py
├── test_api_watermark.py
├── test_auth.py
├── test_auth_google.py
├── test_commands.py
├── test_feedback.py
├── test_health.py
├── test_models.py
├── test_security.py
└── test_support.py
```

Every new blueprint needs a corresponding `tests/test_<blueprint>.py`. Test happy path, auth enforcement, role enforcement, and input validation for every route.

---

## Git & CI/CD

### Branching
```
feature/xyz  →  PR to dev  →  merge to dev  →  PR to main  →  merge to main (deploys)
```

### GitHub Actions workflows

All workflows use **Workload Identity Federation** for GCP auth (no service account keys). Images are pushed to **Artifact Registry** (`europe-west1-docker.pkg.dev`).

| Workflow | Trigger | Actions |
|---|---|---|
| `backend-tests.yml` | Push/PR to `backend/` | pytest |
| `docker-backend.yml` | Push/PR to `backend/` or `main`/`dev` | test → build → push image → deploy (main only) |
| `docker-frontend.yml` | Push/PR to `frontend/` or `main`/`dev` | build (fetches Google client ID from Secret Manager) → push → deploy (main only) |
| `docker-landingpage.yml` | Push/PR to `landingpage/` or `main`/`dev` | build → push → deploy (main only) |
| `terraform.yml` | Push/PR to `terraform/` or `main` | fmt → init → validate → plan → apply (main only) |

Image tagging: `main` → `<sha>` + `latest`, `dev` → `dev-<sha>`, PR → `pr-<sha>` (not pushed).

### Git Hash
The short git hash is injected at build time and available everywhere:
```dockerfile
ARG GIT_SHA=unknown
ENV GIT_HASH=$GIT_SHA
```
```python
# In create_app() — available in all Jinja2 templates as {{ GIT_HASH }}
@app.context_processor
def inject_config():
    return dict(MIN_PASSWORD_LENGTH=MIN_PASSWORD_LENGTH, GIT_HASH=GIT_HASH)
```

---

## Infrastructure (Terraform)

All in `terraform/`. State in GCS bucket. Applied on merge to `main`.

```
GCP region:        europe-west1 (Belgium)
VM region/zone:    europe-west1-b
```

### Modules
- **apis** — Enable required GCP APIs
- **network** — VPC `lumios`, subnet `lumios-{region}` (10.0.0.0/24)
- **artifact_registry** — Docker image registry in europe-west1
- **storage** — GCS photos bucket with lifecycle rules (365d → Nearline, 730d → delete)
- **secrets** — Secret Manager resources
- **vm** — e2-small VM with 50 GB attached disk at `/data` for Postgres + Redis; firewall allows 5432/6379 from subnet only; SSH via IAP only
- **cloudrun** — Three Cloud Run services (backend, frontend, landingpage) with Serverless VPC connector
- **cleanup** — Cloud Scheduler + Cloud Run Job for daily cleanup
- **monitoring** — Uptime checks and email alerting

---

## Cloudflare Setup

```
lumios.niecke-it.de       → proxied CNAME → Cloud Run landingpage
lumios-app.niecke-it.de   → proxied CNAME → Cloud Run frontend
lumios-api.niecke-it.de   → proxied CNAME → Cloud Run backend
```

- Cloudflare terminates SSL — Cloud Run runs HTTP internally
- Thumbnails and previews cached at Cloudflare edge (Cache-Control: public, max-age=31536000)
- API and HTML responses: Cache-Control: no-store

---

## GDPR Notes (Austria / Germany)

- All GCP data in `europe-west1` (EU)
- Audit logs contain IP address → personal data → purge after 90 days
- Customer sessions are anonymous — no name or email collected
- Photographer right-to-erasure: soft-delete → hard-delete after 1 year
- AGB (Terms of Service) acceptance tracked per user (`agb_accepted_at`, `agb_version`)
- DPAs required with: Google Cloud, Brevo, Cloudflare
- Privacy policy + Impressum pages required before go-live

---

## What NOT to do

- Do not add Celery or any async worker — thumbnail generation is inline with Pillow
- Do not use Cloud SQL or Memorystore — Postgres and Redis run on the e2-small VM
- Do not add a GCP Load Balancer — Cloudflare handles routing and SSL
- Do not serve original photos to customers — only preview and thumbnail URLs
- Do not store secrets in code or Docker images — always use Secret Manager / env vars
- Do not use any password hashing other than Argon2id (used for `auth_string` on `local` accounts)
- Do not add separate `password` or `google_sub` columns — all credentials go in `auth_string`; `account_type` tells you how to interpret it
- Do not skip CSRF protection on template state-changing routes (API routes are JWT-authenticated and CSRF-exempt)
- Do not store personal data beyond what is listed in the schema
- Do not write alembic migrations. These should always be generated by alembic itself
- Do not use .env or docker-compose.yml file content for security or performance reports/audits
