# Lumios — Claude Code Guide

Photo library platform for professional photographers. Photographers upload libraries and share them with customers via unique links. Customers view watermarked previews and mark favourites. Photographer is notified when a customer completes their selection.

Domain: **lumios.at** | Open source | Sized for a single photographer initially.

---

## Stack

| Layer | Technology |
|---|---|
| Backend API | Python 3.13, Flask 3.x, Gunicorn, Distroless container |
| Admin UI | Flask + Jinja2 templates, integrated in backend under `/admin` |
| Frontend SPA | React, TanStack Query, TanStack Virtual, React Dropzone, Zustand |
| Database | PostgreSQL 16 (Podman container on e2-small VM) |
| Cache / Sessions | Redis 7 (Podman container on same e2-small VM) |
| File storage | Google Cloud Storage (S3-compatible XML API via boto3) |
| Image processing | Pillow — inline in Flask, no separate worker |
| Auth | Google OAuth 2.0 (photographers + admins); UUID share links (customers) |
| Email | SendGrid transactional API |
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
│   │   │   ├── auth.py       # /auth — Google OAuth, login, logout
│   │   │   ├── libraries.py  # /libraries — CRUD, share link generation
│   │   │   ├── photos.py     # /photos — upload, thumbnail, favourites, mark-done
│   │   │   └── health.py     # /health endpoint for monitoring
│   │   ├── migrations/       # Alembic migration files
│   │   ├── static/
│   │   ├── templates/
│   │   ├── config.py         # All env vars loaded here — fail-fast on missing
│   │   ├── current_user.py   # Thread-local current user helper
│   │   ├── log.py            # Structured JSON logging incl. git_sha field
│   │   ├── main.py           # App factory: create_app()
│   │   ├── models.py         # SQLAlchemy models
│   │   ├── password_handler.py # config for argon2
│   │   └── security.py       # @login_required, @require_role decorators
│   ├── tests/
│   │   ├── conftest.py       # SQLite in-memory fixtures, no external services needed
│   │   ├── test_admin.py
│   │   ├── test_auth.py
│   │   ├── test_models.py
│   │   └── test_security.py
│   ├── Dockerfile            # Multi-stage: builder + distroless runtime
│   ├── entrypoint.py         # Waits for DB, runs flask db upgrade, starts Gunicorn
│   ├── requirements.txt
│   └── requirements-test.txt
├── frontend/                 # React SPA
├── terraform/                # All GCP + Cloudflare infrastructure
├── .github/workflows/        # CI/CD pipelines
├── docker-compose.yml        # Local dev: flask + postgres + redis
├── CLAUDE.md                 # This file
└── TODO.md                   # contains the next steps
```

---

## Commands

```bash
# Local development
podman-compose up                        # Start all services (flask, postgres, redis)
podman-compose up --build                # Rebuild after dependency changes

# Backend (run from backend/)
flask db migrate -m "description"        # Generate new Alembic migration
flask db upgrade                         # Apply migrations
pytest                                   # Run full test suite (SQLite in-memory, no services needed)
ruff check app/ tests/                   # Lint
mypy app/                                # Type check

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

### Optional (with defaults)
| Variable | Default | Description |
|---|---|---|
| `POSTGRES_USER` | `lumios` | DB user |
| `POSTGRES_HOST` | `localhost` | DB host |
| `POSTGRES_PORT` | `5432` | DB port |
| `POSTGRES_DB` | `lumios` | DB name |
| `REDIS_URL` | `None` | Falls back to filesystem sessions if unset |
| `DEBUG` | `false` | Enables hot-reload, disables HTTPS enforcement |
| `GIT_SHA` | `unknown` | Injected at Docker build time |
| `GOOGLE_CLIENT_ID` | — | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | — | Google OAuth client secret |
| `GCS_BUCKET_PHOTOS` | — | GCS bucket name for photo storage |
| `GCS_HMAC_ACCESS_KEY` | — | GCS S3-compatible HMAC key |
| `GCS_HMAC_SECRET` | — | GCS S3-compatible HMAC secret |
| `SENDGRID_API_KEY` | — | SendGrid API key |
| `CLOUDFLARE_ORIGIN_SECRET` | — | Shared secret header to verify requests come via Cloudflare |
| `MAX_LIBRARIES_PER_USER` | `100` | Max libraries a photographer can create |
| `MAX_PHOTOS_PER_LIBRARY` | `500` | Max photos per library |

Never commit `.env`. Never bake secrets into the Docker image.

---

## Database Schema

All models in `backend/app/models.py`. Migrations in `backend/app/migrations/versions/`.

```python
# Key relationships
User          --< roles_users >-- Role          # many-to-many
User (photographer) --< Library                 # one-to-many
Library             --< Photo                   # one-to-many (max 500)
Photo               --< CustomerSelection       # one-to-many
Library / Photo / User --> AuditLog             # append-only
```

### Tables

**users** — `id, email, active (bool), account_type ('local' | 'google'), auth_string (nullable), max_libraries (default 100), created_at, deleted_at`

`account_type` determines how the user authenticates:
- `'local'` — `auth_string` holds an Argon2id-hashed password. Used only for the seeded admin account.
- `'google'` — `auth_string` holds the Google `sub` (subject identifier). Set on first successful OAuth callback.

**roles** — `id, name ('admin' | 'photographer'), description`

**roles_users** — `user_id FK, role_id FK` (junction table, indexed on both columns)

**libraries** — `id, uuid (unique, indexed), photographer_id FK, name, created_at, archived_at, deleted_at`

**photos** — `id, library_id FK, filename, gcs_key_original, gcs_key_preview, gcs_key_thumb, file_size, width, height, content_type, uploaded_at, archived_at`

**customer_selections** — `id, library_id FK, photo_id FK, session_token (anonymous), selected_at`

**audit_logs** — `id, event_type, library_id FK (nullable), photo_id FK (nullable), user_id FK (nullable), ip_address, user_agent, occurred_at`

### Rules
- `deleted_at` is set when a user/library is soft-deleted. Hard delete runs after 1 year via scheduled job.
- `archived_at` is set by lifecycle job after 1 year. GCS lifecycle rule moves object to Nearline storage.
- Audit logs retain for 90 days then are purged (IP address is personal data under GDPR).

---

## Flask App Patterns

Follow the existing codebase conventions precisely:

```python
# Blueprint registration in main.py create_app()
from blueprints.libraries import libraries
app.register_blueprint(libraries)

# Route protection
from security import login_required, require_role

@libraries.route('/libraries', methods=['GET'])
@login_required
def list_libraries():
    ...

@admin.route('/admin/dashboard')
@login_required
@require_role('admin')
def dashboard():
    ...

# DB queries — always use SQLAlchemy 2.x style
from sqlalchemy import select
users = db.session.execute(select(User).where(User.active == True)).scalars().all()

# Audit logging
current_app.logger.info('event description', extra={'log_type': 'audit'})

# Rate limiting — use existing limiter from main.py
from main import limiter

@auth.route('/login', methods=['POST'])
@limiter.limit("2 per second")
def login():
    ...
```

### Security constraints (never skip these)
- All state-changing routes are CSRF-protected via flask-wtf (already global in `create_app`)
- Sessions are server-side in Redis (`SESSION_COOKIE_HTTPONLY=True`, `SAMESITE=Lax`)
- Argon2id for all password hashing via `password_handler.py` — never use any other hash
- flask-talisman enforces HTTPS and CSP in production (`DEBUG=false`)
- Rate limiter is always active — do not bypass it in production code
- Verify the `CLOUDFLARE_ORIGIN_SECRET` header on all incoming requests in production to prevent direct Cloud Run access

---

## GCS File Handling

```python
# GCS key structure
f"photos/{photographer_id}/originals/{photo_id}.jpg"
f"photos/{photographer_id}/previews/{photo_id}.jpg"   # watermarked
f"photos/{photographer_id}/thumbs/{photo_id}.jpg"     # 300px

# Access rules
# - Originals: NEVER served to customers, no signed URLs issued
# - Previews + thumbnails: public GCS URLs, cached by Cloudflare
# - Uploads: Flask receives multipart, validates, then streams to GCS
```

### Upload validation
1. MIME type must be `image/jpeg` or `image/png` — reject everything else
2. Library must have fewer than `MAX_PHOTOS_PER_LIBRARY` photos
3. Photographer must own the library

### Thumbnail generation (inline, no queue)
1. Validate MIME type and library capacity
2. Generate watermarked preview with Pillow (centred semi-transparent text overlay)
3. Generate 300px thumbnail with Pillow
4. Upload all three variants to GCS
5. Insert photo metadata to DB
6. Return photo metadata in response

---

## Share Link Mechanism

```
URL: https://lumios.at/library/<uuid>
- No authentication required
- Backend validates UUID exists and library is active
- Writes audit_log entry on every access (ip_address, user_agent, occurred_at)
- Returns photo metadata list (preview URLs and thumb URLs only — never original)
- Anonymous session token identifies the customer within a session
```

---

## API Endpoints (planned)

```
GET  /health                              # DB ping, returns {status, database, git_sha}

# Auth
GET  /auth/google                         # Redirect to Google OAuth
GET  /auth/callback                       # OAuth callback, sets session
POST /logout                              # Clear session

# Libraries (photographer, login required)
GET  /libraries                           # List photographer's libraries
POST /libraries                           # Create library {name}
GET  /libraries/<id>                      # Library detail + photo list
PATCH /libraries/<id>                     # Rename library
DELETE /libraries/<id>                    # Soft-delete library

# Photos (photographer, login required)
POST /libraries/<id>/photos               # Upload photo (multipart)
DELETE /photos/<id>                       # Delete photo

# Customer (share link, no login)
GET  /library/<uuid>                      # Get library + photo metadata (public)
POST /library/<uuid>/photos/<id>/select   # Toggle favourite
PATCH /library/<uuid>/done                # Mark selection complete → notify photographer

# Admin (admin role required, Jinja2-rendered)
GET  /admin/dashboard
GET/POST /admin/user_create
GET/POST /admin/user_edit/<id>
POST /admin/user_delete/<id>
```

---

## Testing Conventions

Tests use SQLite in-memory — no external services required. Follow `tests/conftest.py` exactly:

```python
# Always set env vars before any app import
os.environ.setdefault("POSTGRES_PASSWORD", "test_password")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars-long!")
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

Every new blueprint needs a corresponding `tests/test_<blueprint>.py`. Test happy path, auth enforcement, role enforcement, and input validation for every route.

---

## Git & CI/CD

### Branching
```
feature/xyz  →  PR to dev  →  merge to dev  →  PR to main  →  merge to main (deploys)
```

### GitHub Actions behaviour
| Trigger | Actions |
|---|---|
| Push to `feature/*` or PR to `dev` | pytest, ruff, mypy, docker build (not pushed) |
| Merge to `dev` | pytest, push image as `dev-<sha>`, deploy to dev Cloud Run |
| Merge to `main` | pytest, push image as `<sha>` + `latest`, terraform apply, deploy to prod |

### Git SHA
The short git SHA is injected at build time and available everywhere:
```dockerfile
ARG GIT_SHA=unknown
ENV GIT_SHA=$GIT_SHA
```
```python
# In create_app() — available in all Jinja2 templates as {{ git_sha }}
@app.context_processor
def inject_git_sha():
    return dict(git_sha=os.environ.get("GIT_SHA", "unknown"))
```
The SHA must appear in: structured log lines, HTML footer, React app footer.

---

## Infrastructure (Terraform)

All in `terraform/`. State in GCS bucket. Applied on merge to `main`.

```
GCP region:        europe-west1 (Belgium)
VM region/zone:    europe-west1-b
GCS backup region: europe-west4 (Netherlands) — cross-region for DR
```

### Key resources
- Cloud Run service + Serverless VPC Access connector (to reach VM on internal IP)
- e2-small VM + 50 GB SSD persistent disk (`/data` mount for Postgres + Redis data)
- Firewall: VM only accepts port 5432/6379 from Cloud Run service account — never public
- GCS buckets: `lumios-photos`, `lumios-static`, `lumios-backups-pg`, `lumios-backups-gcs`, `lumios-tf-state`
- GCS lifecycle rules: archive after 1y (Nearline), delete after 2y
- Object Lock on both backup buckets: 14-day WORM retention
- Cloud Scheduler + Cloud Run Job: daily `pg_dump` → `lumios-backups-pg`
- Storage Transfer: daily GCS photos → `lumios-backups-gcs` (europe-west4)
- Cloud Scheduler: daily cleanup job (soft-delete → hard-delete, audit log purge)
- Secret Manager: all secrets listed in env vars section above
- Cloudflare provider: DNS records, cache rules, origin secret transform rule

---

## Cloudflare Setup

```
lumios.at         → proxied CNAME → Cloud Run *.run.app URL
assets.lumios.at  → proxied CNAME → GCS public bucket URL
```

- Cloudflare terminates SSL — Cloud Run runs HTTP internally
- Thumbnails and previews cached at Cloudflare edge (Cache-Control: public, max-age=31536000)
- API and HTML responses: Cache-Control: no-store
- Origin secret: Cloudflare Transform Rule adds `X-Lumios-Origin-Secret: <value>` to every request. Flask rejects requests missing this header in production.

---

## GDPR Notes (Austria / Germany)

- All GCP data in `europe-west1` (EU)
- Audit logs contain IP address → personal data → purge after 90 days
- Customer sessions are anonymous — no name or email collected
- Photographer right-to-erasure: soft-delete → hard-delete after 1 year
- No tracking, no analytics, no third-party scripts → no cookie banner required
- DPAs required with: Google Cloud, SendGrid, Cloudflare
- Privacy policy + Impressum pages required before go-live (not in this app)

---

## What NOT to do

- Do not add Celery or any async worker — thumbnail generation is inline with Pillow
- Do not use Cloud SQL or Memorystore — Postgres and Redis run on the e2-small VM
- Do not add a GCP Load Balancer — Cloudflare handles routing and SSL
- Do not serve original photos to customers — only preview and thumbnail URLs
- Do not store secrets in code or Docker images — always use Secret Manager / env vars
- Do not use any password hashing other than Argon2id (used for `auth_string` on `local` accounts)
- Do not add separate `password` or `google_sub` columns — all credentials go in `auth_string`; `account_type` tells you how to interpret it
- Do not skip CSRF protection on state-changing routes
- Do not store personal data beyond what is listed in the schema
- Do not write alembic migrations. These should always be generated by alembic itself
