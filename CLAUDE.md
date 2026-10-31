# Lumios — Claude Code Guide

Photo library platform for professional photographers. Photographers upload libraries and share them with customers via unique links. Customers view watermarked previews and mark favourites. Photographer is notified when a customer completes their selection.

Domain: **lumios.niecke-it.de** (landing page), **lumios-app.niecke-it.de** (app) | Open source

---

## Stack

| Layer | Technology |
|---|---|
| Backend API | Python 3.14, Flask 3.x, Gunicorn, python-slim container, uv (package mgmt) |
| Admin UI | Flask + Jinja2 templates, integrated in backend under `/admin` |
| Frontend SPA | React 19, TanStack Query, TanStack Router (file-based), Vite 8, TypeScript |
| Landing page | Separate static site, own nginx Deployment in the k3s cluster |
| Database | PostgreSQL 18 (StatefulSet in k3s, PVC on `local-path`, on the Hetzner node) |
| Cache / Sessions | Redis 8 (Deployment in k3s, no persistence) |
| File storage | S3-compatible object storage (Versity Gateway locally, Hetzner object storage in production) via boto3 |
| Image processing | Pillow — inline in Flask for images; videos (ffmpeg) run on the `video` worker |
| Background jobs | Procrastinate (PostgreSQL-backed queue), worker pods on the backend image — see Background Worker |
| Auth | Google OAuth 2.0 (photographers + admins); JWT tokens for API; UUID share links (customers) |
| Email | Brevo (formerly Sendinblue) transactional API |
| Observability | OpenTelemetry → OTLP exporter (Jaeger locally), off unless `OTEL_EXPORTER_ENDPOINT` is set |
| CDN / SSL / Domain | Cloudflare free plan (proxy, SSL termination, edge caching) |
| IaC | Managed in the separate `Niecke/infrastructure` repo |
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
│   │   │       ├── videos.py         # /api/v1/libraries/<id>/videos — presigned upload, finalize
│   │   │       ├── public.py         # /api/v1/public — share links, waitlist, registration status
│   │   │       ├── notifications.py  # /api/v1/notifications — user notifications
│   │   │       ├── support.py        # /api/v1/support — support tickets
│   │   │       └── feedback.py       # /api/v1/feedback — user feedback/ratings
│   │   ├── services/
│   │   │   ├── audit.py      # Audit log creation helpers
│   │   │   ├── auth.py       # Auth service logic
│   │   │   ├── images.py     # Pillow processing: watermarked preview + thumbnail
│   │   │   ├── mail.py       # Brevo email sending
│   │   │   ├── redis_client.py # Shared Redis client
│   │   │   ├── storage.py    # S3-compatible storage operations
│   │   │   ├── token.py      # JWT token generation/validation
│   │   │   ├── videos.py     # Video validation, ffmpeg probe + thumbnail extraction
│   │   │   ├── workers.py    # Queue/worker state for the admin Workers page, retry + discard of failed jobs
│   │   │   └── zip_stream.py # Streaming ZIP download of a library
│   │   ├── migrations/       # Alembic migration files; procrastinate_schema.py applies the job-queue schema
│   │   ├── static/
│   │   ├── templates/
│   │   ├── tests/
│   │   ├── commands.py       # CLI commands: purge_deleted_accounts, purge_audit_logs, apply_agb_acceptance, seed_test_data
│   │   ├── config.py         # All env vars loaded here — fail-fast on missing
│   │   ├── current_user.py   # Thread-local current user helper
│   │   ├── log.py            # Structured JSON logging
│   │   ├── main.py           # App factory: create_app()
│   │   ├── models.py         # SQLAlchemy models
│   │   ├── password_handler.py # Argon2id config
│   │   ├── security.py       # @login_required, @require_role, @require_api_auth, @require_api_role
│   │   ├── worker.py         # Procrastinate app, queues (default/video/photo), tasks, health check
│   │   ├── tracing.py        # @traced decorator for OpenTelemetry spans
│   │   └── gunicorn_logging.conf
│   ├── Dockerfile            # Multi-stage: builder + python-slim runtime
│   ├── entrypoint.py         # Waits for DB, runs flask db upgrade (unless RUN_MIGRATIONS=false), starts Gunicorn; `migrate` arg = migrate only; `worker --queue <name>` / `worker-health` for the job workers
│   ├── pyproject.toml        # Dependencies (managed via uv)
│   └── uv.lock               # Locked dependency versions
├── frontend/                 # React SPA (TanStack Router file-based routing)
│   ├── src/
│   │   ├── api/              # API client modules (auth, images, libraries, etc.)
│   │   ├── components/       # AppBar, CookieBanner, FeedbackWidget, LanguageSwitcher
│   │   ├── i18n/             # i18next setup (index.ts) + locales/de.json, locales/en.json
│   │   ├── routes/           # File-based routes (TanStack Router): __root, index, login, register, activate, account, support, library.$libraryUuid
│   │   └── main.tsx
│   ├── Dockerfile
│   ├── nginx.conf.template
│   └── package.json
├── landingpage/              # Static landing page (nginx container)
├── charts/lumios/            # Helm chart (published as OCI chart on release)
├── deploy/                   # Flux GitOps manifests for k3s staging/prod (see deploy/README.md)
├── e2e/                      # Playwright end-to-end tests (run by e2e-tests.yml)
├── cloudflare-waf-rules.md   # Cloudflare WAF rule documentation
├── .github/workflows/        # CI/CD pipelines
├── docker-compose.yml        # Local dev: backend, workers, frontend, landingpage, postgres, redis, s3 (Versity Gateway), jaeger
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

# Backend tests run against a real PostgreSQL 18 on tmpfs (fsync off), schema built by the Alembic migrations.
# Start the throwaway test database first (set POSTGRES_TEST_PORT / POSTGRES_PORT if 5432 is taken):
./scripts/test-db.sh start               # or: podman compose --profile test up -d postgres-test
./scripts/test-db.sh stop                # remove it again

# Backend tests (run from backend/)
# only for test setup (uv manages the virtualenv itself, no manual activation needed)
cd backend
uv sync --group test
# for each test run
uv run python -m pytest app/tests/ -v

# Dead code checks (CI runs the ruff check; knip is run manually, it needs npx to bring its own TypeScript 6 because the project uses TypeScript 7)
cd backend && uv run ruff check app/        # F401 / F841, configured in pyproject.toml
cd frontend && npm run knip

# Add/update a backend dependency
cd backend
uv add <package>==<version>          # adds to pyproject.toml + uv.lock
uv lock --upgrade-package <package>  # bump a pinned version

# Background worker (see Background Worker); the Helm chart runs these in the worker pods
python3 /entrypoint.py worker --queue video --concurrency 1   # run a pipeline's worker
python3 /entrypoint.py worker-health                          # exit 0 when database + queue schema answer
python -m procrastinate --app=worker.worker_app shell         # inspect/retry jobs (from app/)

# CLI commands (registered in main.py)
flask purge-deleted-accounts             # Hard-delete accounts soft-deleted > 1 year
flask purge-audit-logs                   # Purge audit logs older than 90 days
flask apply-agb-acceptance               # Apply AGB acceptance after effective date
flask seed-test-data                     # Seed demo data (only runs when DEBUG=true; also run by entrypoint if SEED_TEST_DATA=true)

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
| `REDIS_URL` | `None` | Falls back to filesystem sessions if unset. One shared connection pool (`services/redis_client.py`) serves sessions, caches and the binary preview cache |
| `WATERMARK_PREVIEW_CACHE_MAX_PER_LIBRARY` | `20` | Max cached watermark preview JPEGs per library in Redis (1 h TTL); the oldest are evicted first |
| `WATERMARK_PREVIEW_CACHE_MAX_BYTES` | `2097152` | Watermark previews larger than this (bytes) are served but not cached in Redis |
| `DEBUG` | `false` | Enables hot-reload, disables HTTPS enforcement |
| `GIT_HASH` | `dev` | Injected at Docker build time |
| `APP_VERSION` | `dev` | Release version, set at runtime by the Helm chart from the image tag |
| `BUILD_TIMESTAMP` | `unknown` | Build time, injected as a Docker build arg |
| `GOOGLE_CLIENT_ID` | — | Google OAuth client ID (backend / Jinja2 login) |
| `GOOGLE_CLIENT_SECRET` | — | Google OAuth client secret |
| `GOOGLE_FRONTEND_CLIENT_ID` | — | Separate OAuth client for React frontend (GIS flow) |
| `PUBLIC_BASE_URL` | `http://localhost:8080` | Must match OAuth redirect URIs |
| `FRONTEND_URL` | `http://localhost:5173` | URL of the React frontend |
| `JWT_EXPIRY_SECONDS` | `3600` | JWT token lifetime |
| `S3_ENDPOINT_URL` | `http://s3:7070` | S3-compatible endpoint (Versity Gateway locally, Hetzner object storage in prod) |
| `S3_PUBLIC_ENDPOINT_URL` | same as above | Public URL for presigned URLs (must be browser-reachable) |
| `S3_ACCESS_KEY` | — | S3/HMAC access key |
| `S3_SECRET_KEY` | — | S3/HMAC secret key |
| `S3_BUCKET` | `lumios` | Bucket name |
| `S3_REGION` | `auto` | S3 region name passed to boto3 |
| `VIDEO_UPLOADS_ENABLED` | `false` | Feature gate for the video upload routes |
| `MAX_VIDEO_FILE_SIZE` | `209715200` | Max video size in bytes (200MB) |
| `OTEL_EXPORTER_ENDPOINT` | — | OTLP endpoint (e.g. Jaeger); tracing is enabled when set |
| `SENTRY_DSN` | — | Sentry DSN; error tracking is off while empty |
| `SENTRY_ENVIRONMENT` | — | Sentry environment (`lumios` / `lumios-staging`, set by the Helm chart) |
| `SENTRY_RELEASE` | `$APP_VERSION` | Sentry release (`lumios-backend@<tag>` from the chart) |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.0` | Sentry trace sampling; 0 = errors only |
| `BREVO_API_KEY` | — | Brevo transactional email API key |
| `MAIL_SENDER_EMAIL` | `lumios@niecke-it.de` | Sender email address |
| `MAIL_SENDER_NAME` | `Lumios` | Sender display name |
| `ADMIN_EMAIL` | — | Admin notification email |
| `BREVO_WAITLIST_LIST_ID` | `0` | Brevo contact list for waitlist (0 = disabled) |
| `MAX_USERS` | `100` | Max active users allowed to register |
| `FAILED_LOGIN_MAX_ATTEMPTS` | `5` | Failed password logins per client IP before it is blocked |
| `FAILED_LOGIN_BLOCK_MINUTES` | `15` | How long a client IP stays blocked (Redis TTL; in-memory fallback without Redis) |
| `TRUSTED_PROXY_COUNT` | `1` | Proxies appending to `X-Forwarded-For`; the client IP is that many entries from the right (login lockout) |
| `CURRENT_AGB_VERSION` | `1.0` | Current Terms of Service version |
| `LANDINGPAGE_URL` | `https://lumios.niecke-it.de` | Landing page origin (CORS allowlist) |
| `MAX_CONTENT_LENGTH` | `20MB` | Max upload size |
| `RUN_MIGRATIONS` | `true` | Read by `entrypoint.py`: run `flask db upgrade` before starting Gunicorn. The Helm chart sets `false` on the backend Deployment; the `migrate` hook Job runs `entrypoint.py migrate` instead |

### Secondary configuration

Also read in `backend/app/config.py`, `backend/entrypoint.py` or `services/storage.py`; the defaults are usually fine.

| Variable | Default | Description |
|---|---|---|
| `OTEL_SERVICE_NAME` | `lumios-backend` | Service name reported to tracing |
| `OTEL_SERVICE_VERSION` | `$GIT_HASH` | Service version reported to tracing |
| `VIDEO_JOB_TIMEOUT_SECONDS` | `600` | Upper bound for one ffmpeg call of a video job; a hung process is killed and the job retried |
| `INIT_ADMIN_PASSWORD` | random | Password of the seeded admin; generated (16 chars, letters, digits and `!@#\$%&*`) if empty |
| `MIN_PASSWORD_LENGTH` | `8` | Minimum password length |
| `PASSWORD_HASHER_TIME_COST` | `2` | Argon2id time cost |
| `PASSWORD_HASHER_MEMORY_COST` | `65536` | Argon2id memory cost (KiB) |
| `PASSWORD_HASHER_PARALLELISM` | `4` | Argon2id parallelism |
| `RATELIMIT_ENABLED` | `true` | Rate limiter switch; only disabled in tests |
| `GUNICORN_WORKERS` | `2*cpu+1` | Gunicorn worker count |
| `SEED_TEST_DATA` | unset | `true` makes the entrypoint run `flask seed-test-data` (needs `DEBUG=true`) |
| `SQLALCHEMY_TRACK_MODIFICATIONS` | `false` | Flask-SQLAlchemy modification tracking |
| `SQLALCHEMY_ENGINE_OPTIONS_POOL_PRE_PING` | `true` | Engine option `pool_pre_ping` |
| `SQLALCHEMY_ENGINE_OPTIONS_POOL_RECYCLE` | `3600` | Engine option `pool_recycle` (seconds) |
| `SQLALCHEMY_ENGINE_OPTIONS_POOL_TIMEOUT` | `30` | Engine option `pool_timeout` (seconds) |
| `SQLALCHEMY_ENGINE_OPTIONS_POOL_SIZE` | `3` | Engine option `pool_size` |
| `SQLALCHEMY_ENGINE_OPTIONS_MAX_OVERFLOW` | `3` | Engine option `max_overflow` |

Never commit `.env`. Never bake secrets into the Docker image.

---

## Database Schema

All models in `backend/app/models.py`. Migrations in `backend/app/migrations/versions/`.

```python
# Key relationships
User          --< roles_users >-- Role          # many-to-many
User (photographer) --< Library                 # one-to-many
Library             --< Image                   # one-to-many
Library             --< Video                   # one-to-many
User                --< SupportTicket           # one-to-many
SupportTicket       --< SupportTicketComment    # one-to-many
User                --< Notification            # one-to-many
User                --< Feedback                # one-to-many
User                --> AuditLog                # append-only
```

### Enums

- `SubscriptionType`: `free`, `standard`, `premium`
- `CustomerState`: `none`, `liked`
- `VideoProcessingStatus`: `uploading`, `processing`, `ready`, `failed`
- `NotificationType`: `library_marked`, `library_viewed`, `ticket_comment_added`
- `SupportTicketStatus`: `open`, `closed`
- `AuditLogType`: `user_created`, `user_activated`, `user_deactivated`, `user_reactivated`, `user_deleted`, `password_changed`, `password_set_by_admin`, `login_backend`, `login_frontend`, `login_failed`, `library_created`, `library_edited`, `library_deleted`, `library_finished`, `picture_uploaded`, `picture_deleted`, `picture_downloaded`, `gdpr_export`, `activation_token_resent`, `video_uploaded`, `video_deleted`, `video_downloaded`, `worker_job_retried`, `worker_job_discarded`

### Tables

**users** — `id, email, active, activation_pending, activation_token, account_type ('local' | 'google'), auth_string, created_at, last_login, deleted_at, agb_accepted_at, agb_version, language ('de' | 'en', default 'de'), is_system, subscription (SubscriptionType, default free)`

`account_type` determines how the user authenticates:
- `'local'` — `auth_string` holds an Argon2id-hashed password. Used only for the seeded admin account.
- `'google'` — `auth_string` holds the Google `sub` (subject identifier). Set on first successful OAuth callback.

Quota limits come solely from the subscription tier (`SUBSCRIPTION_LIMITS` in `config.py`). See `User.effective_limits`.

**roles** — `id, name ('admin' | 'photographer'), description`

**roles_users** — `user_id FK, role_id FK` (junction table, indexed on both columns)

**libraries** — `id, uuid (unique, indexed), user_id FK, name, created_at, archived_at, deleted_at, finished_at, use_original_as_preview, download_enabled, is_private, last_viewed_at, watermark_gcs_key, watermark_scale, watermark_position, public_upload_enabled`

**images** — `id, uuid (unique, indexed), library_id FK, s3_key, original_filename, content_type, size, width, height, customer_state (CustomerState, default none), is_external, created_at, deleted_at`

`Image.storage_path(variant)` builds the full S3 key: `photos/{photographer_id}/{library_id}/{variant}/{uuid}.{ext}` where variant is `originals`, `previews`, or `thumbs`.

**videos** — `id, uuid (unique, indexed), library_id FK, s3_key, original_filename, content_type, size, width, height, duration_ms, video_codec, audio_codec, bitrate, processing_status (VideoProcessingStatus, default uploading), hevc_warning, customer_state (CustomerState, default none), is_external, created_at, deleted_at`

`Video.storage_path(variant)` builds `photos/{photographer_id}/{library_id}/originals/{uuid}.{ext}` or `.../thumbs/{uuid}.jpg`. There is no `previews` variant: originals are served for streaming and thumbnails are always JPEG.

`is_external` on `images` and `videos` marks files uploaded by a customer through the public upload routes (`libraries.public_upload_enabled`) rather than by the photographer.

**support_tickets** — `id, user_id FK, subject, body, status (SupportTicketStatus, default open), created_at, updated_at`

**support_ticket_comments** — `id, ticket_id FK, body, created_at`

**notifications** — `id, created_at, seen_at, type (NotificationType), user_id FK, related_object`

**waitlist** — `id, email (unique), created_at`

**audit_logs** — `id (UUIDBinary), audit_type (AuditLogType), ip_address, audit_date (indexed), creator_id FK, related_object_type, related_object_id`

**job_runs** — `id, job_name (indexed), ran_at, status, records_affected, error_message`

**worker_heartbeats** — `hostname (PK), queue_name (indexed), started_at, last_heartbeat` — one row per worker pod, written every 10 s by `entrypoint.py worker`; a pod counts as alive for 30 s. Procrastinate's own `procrastinate_workers` has a heartbeat too but no queue name, so it cannot tell the pipelines apart.

**worker_job_errors** — `job_id (PK), queue_name, task_name, error_message, created_at` — last error line of a job (one truncated line, URLs and paths replaced), shown on the Workers page; removed on retry, discard or success

**feedbacks** — `id, user_id FK, rating, body, admin_note, created_at, updated_at`

**agb_updates** — `id, version, summary, notified_at (indexed), effective_at, applied_at`

### Rules
- `deleted_at` is set when a user/library/image is soft-deleted. Hard delete runs after 1 year via `flask purge-deleted-accounts`.
- `archived_at` on libraries is currently not set by any lifecycle job (the column exists, nothing populates it; issue #435 was closed as not planned). The object storage provider has no storage tiers, so there is no lifecycle rule either; the column stays unused.
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
f"photos/{photographer_id}/{library_id}/thumbs/{uuid}.{ext}"     # 600px longest side

# Access rules
# - Originals: NEVER served to customers, no signed URLs issued
# - Previews + thumbnails: presigned URLs via storage service
# - Image uploads: Flask receives multipart, validates, then streams to S3
# - Video uploads: browser PUTs directly to S3 via presigned URL (see Video Uploads)
```

### Upload validation (images)
1. MIME type must be `image/jpeg`, `image/png` or `image/webp` — reject everything else (videos have their own list, see Video Uploads)
2. Library must have fewer than `max_images_per_library` images (respects subscription tier)
3. Photographer must own the library

### Thumbnail generation for images (inline, no queue)
1. Validate MIME type and library capacity
2. Generate watermarked preview with Pillow (custom watermark image per library, or centred text overlay)
3. Generate thumbnail (600px longest side) with Pillow
4. Upload all three variants to S3
5. Insert image metadata to DB
6. Return image metadata in response

Inline Pillow processing applies to **images only**.

### Video Uploads

Videos are gated by `VIDEO_UPLOADS_ENABLED` and capped by `MAX_VIDEO_FILE_SIZE` (default 200MB). Allowed types: `video/mp4`, `video/quicktime` (MOV), `video/webm`, `video/x-m4v`. The code lives in `blueprints/api/videos.py` (photographer routes), `blueprints/api/public.py` (customer upload routes), `services/videos.py` and `worker.py`.

1. **Init** — `POST .../videos/init` validates type, size and library capacity, creates the `videos` row (`processing_status=uploading`) and returns a presigned S3 PUT URL. The file never passes through Flask.
2. **Upload** — the client PUTs the file straight to S3.
3. **Finalize** — `POST .../videos/<uuid>/finalize` checks the object exists in storage, sets `processing`, and defers a `process_video` job on the `video` queue (see Background Worker).
4. **Process** — the `video` worker runs the job: ffmpeg probes metadata (duration, codecs, bitrate, `hevc_warning`) and extracts one frame, Pillow writes a 600px JPEG thumbnail. Status ends as `ready`, or `failed` after the last retry. A video that is already `ready` is left alone, so a re-run is harmless.
5. **Serving** — there is no preview transcode. Originals are streamed to customers; the thumbnail is the only derived file.

### Background Worker

Jobs are enqueued by the backend and run by separate worker pods. Queue and results live in PostgreSQL ([Procrastinate](https://procrastinate.readthedocs.io), `procrastinate_*` tables), so jobs survive a restart of the backend or a worker. No Celery, no Redis queue.

| Queue | Deployment | Concurrency | Used for |
|---|---|---|---|
| `default` | `worker-default` | 4 | mail jobs (`send_*_email`, `resend_activation`, `services/mail.py`: `notify_*` enqueues, `send_*` sends; 3 runs, a Brevo 4xx other than 429 is not retried); the periodic `recover_stalled_jobs` task (every 5 min) |
| `video` | `worker-video` | 1 | `process_video`: ffmpeg probe + thumbnail |
| `photo` | `worker-photo`, **off by default** | 2 | prepared for image thumbnails/previews, nothing is enqueued on it yet |

- **Code:** `app/worker.py` holds the `procrastinate.App` (`worker_app`), the queue names and the tasks. A task runs inside the Flask app context (`get_flask_app()`). Enqueue from a request with `process_video_task.configure(...).defer(...)` after `open_for_defer()`; import `worker` lazily inside the function, `worker.py` imports the services.
- **Retries:** `process_video` runs at most `VIDEO_MAX_RUNS` (3) times with backoff (7 s, then 11 s). Errors are not swallowed in the service: the exception reaches the worker, which retries. After the last run the job stays in status `failed` (the dead letter, never deleted) and the video is marked `failed`.
- **Idempotency:** `lock=queueing_lock=video-<uuid>` keeps one job per video; a job for a `ready` video returns early.
- **Timeout:** every ffmpeg call is bounded by `VIDEO_JOB_TIMEOUT_SECONDS`; the pod gets `terminationGracePeriodSeconds` to finish a running job.
- **Dead workers:** a job left in `doing` by a killed worker is retried by `recover_stalled_jobs` with the task's retry policy, and ends `failed` once that is used up. Keep `worker-default` enabled.
- **Admin page:** `/admin/workers` (`services/workers.py`) shows per pipeline the queued/running/failed/finished-24h counts, the oldest queued age and the pods' heartbeats, plus running jobs and failed jobs with **Retry** (library `retry_job_by_id`, video back to `processing`) and **Discard** (deletes the failed job; its events cascade). Both are audit logged. The current video step comes from Redis (`worker:video-step:<uuid>`); without `REDIS_URL` it is kept in the worker process only, so the web app shows no step then. A retry counts as one more attempt, so a retried video job runs once more and is not retried again by the policy.
- **Entrypoint:** `python3 /entrypoint.py worker --queue <default|video|photo> [--concurrency N]` waits for the database and runs the worker; `python3 /entrypoint.py worker-health` exits 0 when the database and the queue schema answer (the pods' liveness probe).
- **Local dev:** `podman-compose up` starts `worker-default` and `worker-video`; inspect jobs with `podman exec -it lumios-worker-video /usr/bin/python3 -m procrastinate --app=worker.worker_app shell` (`list_jobs`, `retry <id>`).
- **Schema and upgrades:** the queue tables are created by an Alembic revision that calls `migrations/procrastinate_schema.py::ensure_schema(bind, "<procrastinate migration version>")`. The helper records the applied version in `procrastinate_schema_version` and replays the library's SQL migrations up to that version. `procrastinate[psycopg]` is pinned exactly in `pyproject.toml`; **a bump needs a new Alembic revision** calling `ensure_schema` with the new highest version in `procrastinate/sql/migrations/` (the `pre` and `post` scripts of a version run together in the migrate Job, which is fine while no new pod runs; a later upgrade that ships `pre`/`post` scripts may need the two-step procedure of the Procrastinate docs for rolling workers). `procrastinate_*` tables are excluded from Alembic autogenerate (`include_object`).

---

## Frontend Translations (i18n)

The SPA is available in German (default) and English with `i18next` + `react-i18next`; the `/admin` Jinja pages stay English. Messages live in `frontend/src/i18n/locales/{de,en}.json` (nested keys, e.g. `libraries.title`).

- **Default:** first visit is always German, `navigator.language` is ignored. The choice is stored in `localStorage` (`lumios_locale`) and, for a logged-in photographer, in `users.language` (`PATCH /api/v1/auth/me`); `authApi.me()` applies the account language. `LanguageSwitcher` does both.
- **Add a string:** use `const { t } = useTranslation()` and `t("section.key")`, add the key to **both** `en.json` and `de.json` (plural keys as `key_one` / `key_other`, pass `count`; markup via `<Trans i18nKey=… components={{ strong: <strong /> }} />`). Dates and sizes: `formatDate`, `formatDateTime`, `formatBytes`, `formatTimeAgo` from `i18n/index.ts` (never `toLocaleDateString(undefined, …)`).
- **Backend errors:** the API keeps returning English strings. Map new ones in `frontend/src/api/errors.ts` (`EXACT` table → `errors.*` key) and show them with `getApiErrorMessage(err, t)`; unknown messages are shown as sent.
- **Checks (`npm test`):** `tests/i18n.test.ts` fails when `de.json` and `en.json` differ in keys, a value is empty, a `t("…")` key used in `src/` is missing, or a component has a hard-coded text / `title` / `placeholder` / `aria-label` / `alt`. In `npm run dev` a key missing in German shows the English text prefixed with `[EN] `.
- **Add a language (e.g. `fr`):** copy `en.json` to `locales/fr.json` and translate it; register it in `i18n/index.ts` (import, `resources`, `SUPPORTED_LOCALES`); allow it in `SUPPORTED_LANGUAGES` in `blueprints/api/auth.py` (and the `users.language` length if needed); add `language.fr` to all locale files; extend `UserInfo.language` in `api/auth.ts`.
- German wording: Library → *Galerie*, photo → *Foto*, watermark → *Wasserzeichen*, selection → *Auswahl*, share link → *Freigabe-Link*, formal address (*Sie*). Transactional mails (`services/mail.py`) are German only.

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
GET  /version                                       # Public build identity {commit, version, built_at}

# Auth (template-based, session)
GET  /login                                         # Login page
POST /login                                         # Session login
GET  /auth/google                                   # Redirect to Google OAuth
GET  /auth/callback                                 # OAuth callback, sets session
POST /logout                                        # Clear session

# API Auth (/api/v1/auth, JWT)
GET  /api/v1/auth/me                                # Current user info (incl. `language`)
PATCH /api/v1/auth/me                               # Update own preferences {language: 'de' | 'en'}
POST /api/v1/auth/login                             # JWT login (email/password)
POST /api/v1/auth/google/verify                     # Verify Google ID token
POST /api/v1/auth/google/callback                   # Google OAuth code exchange
POST /api/v1/auth/exchange                          # Exchange session for JWT
POST /api/v1/auth/register                          # Register new account
POST /api/v1/auth/google/register                   # Register via Google
POST /api/v1/auth/activate                          # Activate account with token
POST /api/v1/auth/change_password                   # Change password
POST /api/v1/auth/resend-activation                 # Resend activation email by {email} (always 200 for a well-formed address, no enumeration; a `resend_activation` job does the lookup; limited per client IP and per address, one waiting job per address) or legacy {token}
DELETE /api/v1/auth/account                         # Delete own account (soft-delete)

# Libraries (/api/v1/libraries, JWT, photographer role)
GET  /api/v1/libraries                              # List photographer's libraries
POST /api/v1/libraries                              # Create library {name}
GET  /api/v1/libraries/uuid/<uuid>                  # Library detail by UUID
PATCH /api/v1/libraries/<id>                        # Update library settings
DELETE /api/v1/libraries/<id>                        # Soft-delete library
POST /api/v1/libraries/<id>/watermark               # Upload custom watermark
DELETE /api/v1/libraries/<id>/watermark              # Remove watermark
GET  /api/v1/libraries/<id>/watermark/preview        # Preview watermark on sample image
POST /api/v1/libraries/<id>/watermark/apply          # Apply watermark settings

# Images (/api/v1/libraries/<id>/images, JWT, photographer role)
GET  /api/v1/libraries/<id>/images                  # List images in library
POST /api/v1/libraries/<id>/images                  # Upload image (multipart)
DELETE /api/v1/libraries/<id>/images/<image_id>      # Delete image

# Videos (/api/v1/libraries/<id>/videos, JWT, photographer role, VIDEO_UPLOADS_ENABLED)
POST /api/v1/libraries/<id>/videos/init                      # Create video row + presigned PUT URL
POST /api/v1/libraries/<id>/videos/<video_uuid>/finalize     # Confirm upload, start processing
GET  /api/v1/libraries/<id>/videos/<video_uuid>              # Video metadata / processing status
DELETE /api/v1/libraries/<id>/videos/<video_id>              # Delete video

# Public (/api/v1/public, no auth)
GET  /api/v1/public/libraries/<uuid>                # Get library + image metadata (share link)
PATCH /api/v1/public/libraries/<uuid>/images/<image_uuid>/state  # Set customer state (liked/none)
PATCH /api/v1/public/libraries/<uuid>/videos/<video_uuid>/state  # Set customer state (liked/none)
POST /api/v1/public/libraries/<uuid>/finish          # Mark selection complete
GET  /api/v1/public/libraries/<uuid>/images/<id>/download  # Download original (if enabled)
GET  /api/v1/public/libraries/<uuid>/download        # Stream all images as ZIP (if enabled)
POST /api/v1/public/libraries/<uuid>/images          # Customer image upload (if public_upload_enabled)
POST /api/v1/public/libraries/<uuid>/videos/init     # Customer video upload: presigned PUT URL
POST /api/v1/public/libraries/<uuid>/videos/<video_uuid>/finalize  # Customer video upload: finalize
GET  /api/v1/public/libraries/<uuid>/videos/<video_uuid>           # Video metadata / status
GET  /api/v1/public/libraries/<uuid>/videos/<video_uuid>/download  # Download video original (if enabled)
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
GET  /                                              # Admin index / dashboard
GET  /admin/users
GET/POST /admin/user_create
GET/POST /admin/user_edit/<id>
GET/POST /change_password
GET/POST /admin/set_password/<id>
POST /admin/user_delete/<id>
POST /admin/user_activate/<id>                      # Activate a pending user (clears token, audit user_activated)
POST /admin/user_resend_activation/<id>             # Fresh 72 h token + mail for a pending user (audit activation_token_resent)
POST /admin/user_gdpr_export/<user_id>
GET  /admin/support
GET  /admin/support/<ticket_id>
POST /admin/support/<ticket_id>/comment
POST /admin/support/<ticket_id>/close
GET  /admin/feedback
POST /admin/feedback/<feedback_id>/note
GET/POST /admin/notify_agb
GET  /admin/system                                  # Build info, dependency checks, job recency
GET  /admin/workers                                 # Queue counts, worker pods, running + failed jobs
POST /admin/workers/jobs/<id>/retry                 # Queue a failed job again (audit worker_job_retried)
POST /admin/workers/jobs/<id>/discard               # Delete a failed job (audit worker_job_discarded)
GET  /admin/auditlogs
```

---

## Testing Conventions

Tests run against a real PostgreSQL (same major version as production) whose data directory is on tmpfs with `fsync`, `synchronous_commit` and `full_page_writes` off. Start it with `./scripts/test-db.sh start` (CI uses a `postgres` service container). The `app` fixture creates the `lumios_test` database if missing, rebuilds the schema by running the Alembic migrations once per session, and fails with startup instructions if PostgreSQL is unreachable. `clean_db` deletes all rows after each test. `tests/test_migrations.py` fails when the migrations and the models disagree (including enum values). Follow `tests/conftest.py` exactly:

```python
# Always set env vars before any app import
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_USER", "lumios")
os.environ.setdefault("POSTGRES_PASSWORD", "test_password")
os.environ.setdefault("POSTGRES_DB", "lumios_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars-long!")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-key-at-least-32-chars-long!")
os.environ.setdefault("DEBUG", "true")  # disables Talisman HTTPS enforcement

# Use minimal Argon2 params — hashing is slow otherwise
os.environ.setdefault("PASSWORD_HASHER_TIME_COST", "1")
os.environ.setdefault("PASSWORD_HASHER_MEMORY_COST", "8")
os.environ.setdefault("PASSWORD_HASHER_PARALLELISM", "1")

# The database URI comes from config.py (POSTGRES_* above); no override needed
test_config = {
    "TESTING": True,
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
├── test_api_images.py        # also the merged photo + video media list
├── test_api_libraries.py
├── test_api_public.py        # also the public video routes and the ZIP download with videos
├── test_api_videos.py        # photographer video routes: gate, auth, scoping, init/finalize/get/delete, quotas
├── test_api_watermark.py
├── test_auth.py
├── test_auth_google.py
├── test_commands.py
├── test_entrypoint.py
├── test_feedback.py
├── test_health.py
├── test_login_protection.py
├── test_mail.py
├── test_migrations.py
├── test_models.py
├── test_procrastinate_schema.py
├── test_quota.py
├── test_redis_client.py
├── test_security.py
├── test_sentry.py
├── test_storage.py
├── test_support.py
├── test_tracing.py
├── test_videos.py            # services/videos.py: validation, init, finalize, process_video, ffmpeg parsing, steps
├── test_worker.py            # queue round trip: enqueue, run, retry, dead letter, health
└── test_zip_stream.py
```

**Video coverage:** the photographer and public video routes (`test_api_videos.py`, `test_api_public.py`), `services/videos.py` (`test_videos.py`) and `services/zip_stream.py` are covered with storage, ffmpeg and Redis mocked. The queue round trip of `process_video` is in `test_worker.py`. Nothing runs a real ffmpeg binary on a real video file.

Every new blueprint needs a corresponding `tests/test_<blueprint>.py`. Test happy path, auth enforcement, role enforcement, and input validation for every route.

---

## Git & CI/CD

### Branching
Trunk-based: `main` is the only long-lived branch. `dev` is retired; never branch from it.

```
feature/xyz  →  PR to main  →  merge to main (deploys staging)  →  merge release-please PR (deploys production)
```

Some workflow triggers below still list `dev` (and `release/**`); those entries are leftovers, nothing is merged to `dev` any more.

### GitHub Actions workflows

Container images live in **GHCR** (`ghcr.io/niecke/lumios/{backend,frontend,landingpage}`) and are pushed with `GITHUB_TOKEN`. Workflows never deploy directly: Flux on the k3s node pulls the new tags (see `deploy/README.md`).

| Workflow | Trigger | Actions |
|---|---|---|
| `commitlint.yml` | PR to `main`/`dev`/`release/**` | PR title must be a conventional commit |
| `ci.yml` | PR to `main`/`dev`/`release/**` | detect code changes → backend tests → build multi-arch (`linux/amd64,linux/arm64`) images, push as `ci-<head_sha40>` |
| `backend-tests.yml` | Push/PR to `backend/`, called by `ci.yml` | pytest |
| `e2e-tests.yml` | PR to `main`/`dev` | docker compose integration tests |
| `promote.yml` | Push to `main`/`release/**` | retag the tested `ci-<sha40>` digests to `sha-<main_sha7>` (no rebuild); update `deploy/flux/staging/helmrelease.yaml` if it exists |
| `release-please.yml` | Push to `main`/`release/**` | keep a release PR open (version bumps + `CHANGELOG.md`); merging it tags `vX.Y.Z` and creates the GitHub Release |
| `release.yml` | Tag `vX.Y.Z` | retag images `vX.Y.Z` + `stable`/`X.Y`/`X` by digest, publish Helm chart to `oci://ghcr.io/niecke/lumios/charts` (if `charts/lumios` exists), cosign-sign, Syft SBOM attestations, digests table in release notes |

Image tagging: PR → `ci-<head_sha40>`, merge to `main` → `sha-<main_sha7>`, release → `vX.Y.Z` (+ floating tags).

### Conventional Commits and releases

PRs are squash-merged, so the **PR title** is the commit release-please reads (`feat:` → minor, `fix:` → patch, `feat!:` → major; `chore`, `docs`, `ci`, … → no release). Never bump versions or edit `CHANGELOG.md` by hand: release-please owns `.release-please-manifest.json`, `backend/pyproject.toml`, `backend/uv.lock` and `charts/lumios/Chart.yaml`.

Optional secrets: `RELEASE_PLEASE_TOKEN` (PAT; without it the release PR and tag do not trigger further workflows) and `DEPLOY_KEY` (deploy key used by `promote.yml`/`release.yml` to push deploy commits to a protected `main`). Both live as secrets of the GitHub Environment `release`, not as repository secrets; the environment admits only `main` and `v*` tags, so a run from another branch cannot read them. The `release-please`, `promote` and `release` jobs set `environment: release`. Setup: `deploy/README.md`.

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

## Infrastructure

Staging and production run on one Hetzner node (CAX21, k3s) with Hetzner object storage. The node, volume and DNS are managed in the separate `Niecke/infrastructure` repository; this repo holds no Terraform. Deployment is Flux GitOps with the Helm chart in `charts/lumios/`, see `deploy/README.md`.

---

## Cloudflare and Ingress Setup

```
lumios.niecke-it.de       → landingpage Service
lumios-app.niecke-it.de   → frontend Service (/api/ → backend Service)
lumios-api.niecke-it.de   → backend Service
(staging: lumios-staging, lumios-app-staging, lumios-api-staging)
```

- DNS records point at the Hetzner k3s node; Cloudflare may proxy them
- Traefik (shipped with k3s) is the ingress controller, one Ingress per host plus Traefik Middlewares (`charts/lumios/templates/ingress.yaml`)
- cert-manager issues one Let's Encrypt certificate per host (ClusterIssuer `letsencrypt`)
- Thumbnails and previews cached at Cloudflare edge (Cache-Control: public, max-age=31536000)
- API and HTML responses: Cache-Control: no-store

---

## GDPR Notes (Austria / Germany)

- Application data (database, object storage) lives on Hetzner in the EU
- Audit logs contain IP address → personal data → purge after 90 days
- Customer sessions are anonymous — no name or email collected
- Photographer right-to-erasure: soft-delete → hard-delete after 1 year
- AGB (Terms of Service) acceptance tracked per user (`agb_accepted_at`, `agb_version`)
- DPAs required with the processors in use: Hetzner, Cloudflare, Brevo, Sentry
- Google Cloud stays a processor only if it is still used for the off-site database and photo backups (#411). Owner decision, to be reflected in the privacy policy (#517)
- Privacy policy + Impressum pages required before go-live

---

## What NOT to do

- Do not add Celery or a second queue system — background jobs run on the Procrastinate workers; image thumbnail generation stays inline with Pillow until the `photo` pipeline is enabled
- Do not use Cloud SQL or Memorystore — Postgres and Redis run in the k3s cluster on the Hetzner node
- Do not add a cloud load balancer — Traefik is the ingress, cert-manager handles certificates, Cloudflare may proxy in front
- Do not serve original photos to customers — only preview and thumbnail URLs
- Do not store secrets in code or Docker images — inject them through env vars from Kubernetes Secrets (`lumios-values`, see `deploy/README.md`)
- Do not use any password hashing other than Argon2id (used for `auth_string` on `local` accounts)
- Do not add separate `password` or `google_sub` columns — all credentials go in `auth_string`; `account_type` tells you how to interpret it
- Do not skip CSRF protection on template state-changing routes (API routes are JWT-authenticated and CSRF-exempt)
- Do not store personal data beyond what is listed in the schema
- Do not write alembic migrations. These should always be generated by alembic itself (the Procrastinate revisions are generated empty with `flask db revision` and then call `ensure_schema`)
- Do not use .env or docker-compose.yml file content for security or performance reports/audits
