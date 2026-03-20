from flask import Flask, session
from authlib.integrations.flask_client import OAuth
from log import setup_app_logger
from config import (
    POSTGRES_USER,
    POSTGRES_PASSWORD,
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_DB,
    SECRET_KEY,
    SQLALCHEMY_TRACK_MODIFICATIONS,
    SQLALCHEMY_ENGINE_OPTIONS,
    DEBUG,
    REDIS_URL,
    MIN_PASSWORD_LENGTH,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    MAX_CONTENT_LENGTH,
    GIT_HASH,
    CLOUD_TRACE_ENABLED,
    GOOGLE_CLOUD_PROJECT,
    CLOUD_TRACE_SERVICE,
    CLOUD_TRACE_SERVICE_VERSION,
    OTEL_EXPORTER_ENDPOINT,
)
from models import User
from current_user import current_user
from flask_talisman import Talisman
from flask_wtf.csrf import CSRFProtect
from flask_session import Session
from flask import request as _request
from flask_limiter import Limiter


def _get_real_ip() -> str:
    """Extract client IP from X-Forwarded-For (trusted behind Cloud Run / Nginx)."""
    forwarded = _request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return _request.remote_addr


csrf = CSRFProtect()
server_session = Session()
if REDIS_URL:
    limiter = Limiter(
        key_func=_get_real_ip,
        default_limits=["10 per second"],
        storage_uri=REDIS_URL,
    )
else:
    limiter = Limiter(
        key_func=_get_real_ip,
        default_limits=["10 per second"],
        storage_uri="memory://",
    )


oauth = OAuth()


def _init_cloud_trace(app: Flask) -> None:
    """Set up OpenTelemetry tracing with Cloud Trace or OTLP (Jaeger) exporter."""
    if not CLOUD_TRACE_ENABLED:
        return
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.instrumentation.flask import FlaskInstrumentor

    resource = Resource.create(
        {
            "service.name": CLOUD_TRACE_SERVICE,
            "service.version": CLOUD_TRACE_SERVICE_VERSION,
        }
    )
    provider = TracerProvider(resource=resource)

    if OTEL_EXPORTER_ENDPOINT:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(endpoint=OTEL_EXPORTER_ENDPOINT, insecure=True)
    else:
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

        exporter = CloudTraceSpanExporter(project_id=GOOGLE_CLOUD_PROJECT or None)

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    FlaskInstrumentor().instrument_app(app)

    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    SQLAlchemyInstrumentor().instrument()


def create_app(test_config=None):
    app = Flask(__name__)

    _init_cloud_trace(app)
    app.logger.info(
        f"Cloud Trace: {'enabled' if CLOUD_TRACE_ENABLED else 'disabled'}",
        extra={"log_type": "startup"},
    )

    if DEBUG:
        app.config["DEBUG"] = True  # Auto-reloads templates!
        app.jinja_env.auto_reload = True
        app.jinja_env.cache = None

    # Config
    app.config["SECRET_KEY"] = SECRET_KEY
    app.config["SQLALCHEMY_DATABASE_URI"] = (
        f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = SQLALCHEMY_TRACK_MODIFICATIONS
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = SQLALCHEMY_ENGINE_OPTIONS

    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

    # Allow tests to override any config value before extensions are initialised
    if test_config is not None:
        app.config.update(test_config)

    # Logging
    setup_app_logger(app)

    # Server-side sessions (Redis if available, filesystem fallback)
    if REDIS_URL:
        import redis

        app.config["SESSION_TYPE"] = "redis"
        app.config["SESSION_REDIS"] = redis.from_url(REDIS_URL)
        app.logger.info(f"Sessions: Redis ({REDIS_URL})", extra={"log_type": "startup"})
    else:
        app.config["SESSION_TYPE"] = "filesystem"
        app.config["SESSION_FILE_DIR"] = "/tmp/flask_sessions"
        app.logger.info(
            "Sessions: filesystem (no REDIS_URL set)", extra={"log_type": "startup"}
        )
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = not DEBUG
    server_session.init_app(app)

    # enable caching
    limiter.init_app(app)

    # Init extensions
    from models import db, migrate

    db.init_app(app)
    migrate.init_app(app, db)

    # Google OAuth
    app.config["GOOGLE_CLIENT_ID"] = GOOGLE_CLIENT_ID
    app.config["GOOGLE_CLIENT_SECRET"] = GOOGLE_CLIENT_SECRET
    oauth.init_app(app)
    oauth.register(
        name="google",
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email"},
    )

    # Security extensions
    csrf.init_app(app)
    Talisman(
        app,
        force_https=not DEBUG,
        strict_transport_security=not DEBUG,
        content_security_policy={
            "default-src": "'self'",
            # GIS client script
            "script-src": "'self' https://accounts.google.com/gsi/client",
            # GIS renders its button with inline styles
            "style-src": "'self' https://accounts.google.com/gsi/ 'unsafe-inline'",
            # Profile pictures come from Google's CDN
            "img-src": "'self' data: https://lh3.googleusercontent.com",
            "font-src": "'self'",
            # GIS uses an iframe for the One Tap / button flow
            "frame-src": "https://accounts.google.com/gsi/",
            # GIS makes XHR calls back to Google
            "connect-src": "'self' https://accounts.google.com/gsi/",
        },
    )

    # add current_user to each request
    @app.before_request
    def load_current_user():
        user_id = session.get("user_id")
        if user_id:
            current_user.set_user(db.session.get(User, user_id))
        else:
            current_user.set_user(None)

    # add current_user to jinja templates
    @app.context_processor
    def inject_current_user():
        return dict(current_user=current_user)

    # add require_role function to jinja tempaltes
    @app.context_processor
    def utility_functions():
        def require_role(role_name):
            return current_user.has_role(role_name)

        return dict(require_role=require_role)

    @app.context_processor
    def inject_config():
        return dict(MIN_PASSWORD_LENGTH=MIN_PASSWORD_LENGTH, GIT_HASH=GIT_HASH)

    # Register blueprints
    from blueprints.auth import auth

    app.register_blueprint(auth)

    from blueprints.admin import admin

    app.register_blueprint(admin)

    from blueprints.health import health

    app.register_blueprint(health)

    from blueprints.api import api
    from blueprints.api.auth import auth_api
    from blueprints.api.libraries import libraries_api
    from blueprints.api.images import images_api
    from blueprints.api.public import public_api
    from blueprints.api.notifications import notifications_api

    # csrf.exempt only covers the named blueprint's own views. Child blueprints
    # registered on a parent have their own blueprint name ("auth_api", not "api"),
    # so each one must be exempted explicitly.
    csrf.exempt(api)
    csrf.exempt(auth_api)
    csrf.exempt(libraries_api)
    csrf.exempt(images_api)
    csrf.exempt(public_api)
    csrf.exempt(notifications_api)
    app.register_blueprint(api)

    return app
