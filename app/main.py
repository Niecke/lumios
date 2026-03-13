from flask import Flask, session
from flask_migrate import Migrate
from log import setup_app_logger
from config import (
    MYSQL_USER, MYSQL_PASSWORD, MYSQL_HOST, MYSQL_PORT, MYSQL_DB,
    SECRET_KEY, SQLALCHEMY_TRACK_MODIFICATIONS, SQLALCHEMY_ENGINE_OPTIONS, DEBUG, REDIS_URL,
    MIN_PASSWORD_LENGTH
)
from models import User
from current_user import current_user
from flask_talisman import Talisman
from flask_wtf.csrf import CSRFProtect
from flask_session import Session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

csrf = CSRFProtect()
server_session = Session()
if REDIS_URL:
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["10 per second"],
        storage_uri=REDIS_URL
    )
else:
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["10 per second"],
        storage_uri="memory://"
    )

migrate = Migrate()

def create_app(test_config=None):
    app = Flask(__name__)

    if DEBUG:
        app.config['DEBUG'] = True  # Auto-reloads templates!
        app.jinja_env.auto_reload = True
        app.jinja_env.cache = None

    # Config
    app.config['SECRET_KEY'] = SECRET_KEY
    app.config['SQLALCHEMY_DATABASE_URI'] = (
        f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
        "?ssl_disabled=0&client_flag=4"
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = SQLALCHEMY_TRACK_MODIFICATIONS
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = SQLALCHEMY_ENGINE_OPTIONS

    # Allow tests to override any config value before extensions are initialised
    if test_config is not None:
        app.config.update(test_config)
    
    # Logging
    setup_app_logger(app)
    
    # Server-side sessions (Redis if available, filesystem fallback)
    if REDIS_URL:
        import redis
        app.config['SESSION_TYPE'] = 'redis'
        app.config['SESSION_REDIS'] = redis.from_url(REDIS_URL)
        app.logger.info(f'Sessions: Redis ({REDIS_URL})', extra={'log_type': 'startup'})
    else:
        app.config['SESSION_TYPE'] = 'filesystem'
        app.config['SESSION_FILE_DIR'] = '/tmp/flask_sessions'
        app.logger.info('Sessions: filesystem (no REDIS_URL set)', extra={'log_type': 'startup'})
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    server_session.init_app(app)

    # enable caching
    limiter.init_app(app)

    # Init extensions
    from models import db
    db.init_app(app)
    migrate.init_app(app, db)

    # Security extensions
    csrf.init_app(app)
    Talisman(app,
        force_https=not DEBUG,
        content_security_policy={
            'default-src': "'self'",
            'script-src': "'self'",
            'style-src': "'self'",
            'img-src': "'self' data:",
            'font-src': "'self'",
        }
    )
    
    # add current_user to each request 
    @app.before_request
    def load_current_user():
        user_id = session.get('user_id')
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
        return dict(MIN_PASSWORD_LENGTH=MIN_PASSWORD_LENGTH)

    # Register blueprints/routes
    from routes import bp as main_bp
    app.register_blueprint(main_bp)

    from blueprints.admin import admin
    app.register_blueprint(admin)

    from blueprints.documents import documents
    app.register_blueprint(documents)

    # Limit upload request size to 64 MB
    app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024

    return app
