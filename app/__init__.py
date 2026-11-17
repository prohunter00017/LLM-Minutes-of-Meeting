import os
from datetime import datetime, timezone
from flask import Flask, render_template
from app.config import Config
from app.extensions import db, login_manager, celery


def create_app(config_class=Config) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    # Ensure required directories exist
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)

    # Configure Celery
    celery.conf.update(
        broker_url=app.config["CELERY_BROKER_URL"],
        result_backend=app.config["CELERY_RESULT_BACKEND"],
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_track_started=True,
        beat_schedule={
            "cleanup-expired-meetings": {
                "task": "app.tasks.cleanup.cleanup_expired_meetings",
                "schedule": 3600.0,  # every hour
            },
            "cleanup-demo-meetings": {
                "task": "app.tasks.cleanup.cleanup_demo_meetings",
                "schedule": 600.0,  # every 10 minutes
            },
            "reset-monthly-uploads": {
                "task": "app.tasks.billing.reset_monthly_uploads",
                "schedule": 86400.0,  # every 24 hours
            },
        },
    )

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask

    # Register blueprints
    from app.auth.routes import auth_bp
    from app.dashboard.routes import dashboard_bp
    from app.meetings.routes import meetings_bp
    from app.admin.routes import admin_bp
    from app.api.routes import api_bp
    from app.demo.routes import demo_bp
    from app.legal.routes import legal_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(meetings_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(demo_bp)
    app.register_blueprint(legal_bp)

    # Billing blueprint (loads lazily so Stripe key can be missing during install)
    try:
        from app.billing.routes import billing_bp
        app.register_blueprint(billing_bp)
    except Exception:
        pass

    # Error handlers
    @app.errorhandler(404)
    def not_found_page(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template("errors/500.html"), 500

    # Lightweight health probe — used by load balancers / uptime checks.
    # Never touches third-party APIs so it stays fast and can't fail on a bad key.
    @app.route("/health")
    def health():
        from datetime import datetime, timezone
        return {
            "status": "ok",
            "service": "intelliforge",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, 200

    # User loader for Flask-Login
    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Create tables and seed data
    with app.app_context():
        db.create_all()
        _migrate_db()
        _seed_defaults(app)

    return app


def _migrate_db() -> None:
    """Migrate SQLite schema to support new features."""
    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)

    # Migrate meetings table
    if inspector.has_table("meetings"):
        columns_info = {c["name"]: c for c in inspector.get_columns("meetings")}
        needs_recreate = False
        if "is_demo" not in columns_info or "session_token" not in columns_info:
            needs_recreate = True
        elif columns_info.get("user_id", {}).get("nullable") is not True:
            needs_recreate = True

        if needs_recreate:
            with db.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE meetings_new (
                        id INTEGER NOT NULL PRIMARY KEY,
                        user_id INTEGER,
                        title VARCHAR(200) NOT NULL,
                        original_filename VARCHAR(255) NOT NULL,
                        stored_filename VARCHAR(255) NOT NULL,
                        file_size BIGINT,
                        status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        task_id VARCHAR(255),
                        progress INTEGER DEFAULT 0,
                        error_message TEXT,
                        transcript TEXT,
                        minutes_of_meeting TEXT,
                        created_at DATETIME,
                        expires_at DATETIME,
                        deleted_at DATETIME,
                        is_demo BOOLEAN DEFAULT 0,
                        session_token VARCHAR(64)
                    )
                """))
                old_cols = [c["name"] for c in inspector.get_columns("meetings")]
                cols_to_copy = [c for c in old_cols if c not in ("is_demo", "session_token")]
                cols_str = ", ".join(cols_to_copy)
                conn.execute(text(f"INSERT INTO meetings_new ({cols_str}) SELECT {cols_str} FROM meetings"))
                conn.execute(text("DROP TABLE meetings"))
                conn.execute(text("ALTER TABLE meetings_new RENAME TO meetings"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_meetings_session_token ON meetings (session_token)"))
                conn.commit()

    # Migrate users table — add subscription columns
    if inspector.has_table("users"):
        user_cols = {c["name"] for c in inspector.get_columns("users")}
        with db.engine.connect() as conn:
            if "plan" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN plan VARCHAR(20) DEFAULT 'free'"))
            if "plan_period_start" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN plan_period_start DATETIME"))
            if "plan_uploads_used" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN plan_uploads_used INTEGER DEFAULT 0"))
            if "plan_is_annual" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN plan_is_annual BOOLEAN DEFAULT 0"))
            if "subscription_status" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN subscription_status VARCHAR(20) DEFAULT 'active'"))
            if "stripe_customer_id" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN stripe_customer_id VARCHAR(255)"))
            if "stripe_subscription_id" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN stripe_subscription_id VARCHAR(255)"))
            if "stripe_price_id" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN stripe_price_id VARCHAR(255)"))
            conn.commit()


def _seed_defaults(app: Flask) -> None:
    from app.models import User, SystemConfig
    from app.config import Config
    from sqlalchemy.exc import IntegrityError

    # Seed admin user — create if missing, always sync password from .env
    # Race-safe: celery worker + beat + web all start together and may seed
    # concurrently, so catch the UNIQUE violation and re-query the winner.
    admin = User.query.filter_by(username=app.config["ADMIN_USERNAME"]).first()
    if not admin:
        admin = User(
            username=app.config["ADMIN_USERNAME"],
            email=app.config["ADMIN_EMAIL"],
            role="admin",
            is_active=True,
        )
        db.session.add(admin)
        admin.set_password(app.config["ADMIN_PASSWORD"])
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            admin = User.query.filter_by(username=app.config["ADMIN_USERNAME"]).first()
    else:
        # Always update password so .env changes take effect on restart
        admin.set_password(app.config["ADMIN_PASSWORD"])
        db.session.commit()

    # Seed / sync system config from .env
    # always_update=True  -> .env is the source of truth, overwrites DB on every restart
    # always_update=False -> DB wins (admin panel edits are preserved)
    defaults = [
        ("llm_base_url", app.config["LLM_BASE_URL"], "LLM API base URL", False, True),
        ("llm_api_key", app.config["LLM_API_KEY"], "LLM API key", True, True),
        ("llm_model", app.config["LLM_MODEL"], "LLM model name", False, True),
        ("speech_provider", app.config["SPEECH_PROVIDER"], "Active speech-to-text provider", False, True),
        ("deepgram_api_key", app.config["DEEPGRAM_API_KEY"], "Deepgram API key", True, True),
        ("assemblyai_api_key", app.config["ASSEMBLYAI_API_KEY"], "AssemblyAI API key", True, True),
        ("sarvam_api_key", app.config["SARVAM_API_KEY"], "Sarvam AI API key", True, True),
        ("elevenlabs_api_key", app.config["ELEVENLABS_API_KEY"], "ElevenLabs API key", True, True),
        ("meeting_retention_days", str(app.config["MEETING_RETENTION_DAYS"]), "Days before uploaded files are auto-deleted", False, False),
        ("max_upload_size_mb", str(app.config.get("MAX_CONTENT_LENGTH", 500 * 1024 * 1024) // (1024 * 1024)), "Maximum upload file size in MB", False, False),
    ]
    for key, value, description, is_sensitive, always_update in defaults:
        existing = SystemConfig.query.filter_by(key=key).first()
        if not existing:
            db.session.add(SystemConfig(key=key, value=value, description=description, is_sensitive=is_sensitive))
        elif always_update:
            existing.value = value
            existing.updated_at = datetime.now(timezone.utc)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
