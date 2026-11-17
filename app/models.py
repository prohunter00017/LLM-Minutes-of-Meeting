from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user")  # admin | user
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Subscription / billing
    plan = db.Column(db.String(20), nullable=False, default="free")  # free | starter | pro
    plan_period_start = db.Column(db.DateTime, nullable=True)
    plan_uploads_used = db.Column(db.Integer, nullable=False, default=0)
    plan_is_annual = db.Column(db.Boolean, nullable=False, default=False)
    subscription_status = db.Column(db.String(20), nullable=False, default="active")  # active | canceled | past_due | unpaid
    stripe_customer_id = db.Column(db.String(255), nullable=True)
    stripe_subscription_id = db.Column(db.String(255), nullable=True)
    stripe_price_id = db.Column(db.String(255), nullable=True)

    meetings = db.relationship("Meeting", backref="owner", lazy="dynamic")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role})>"


class Meeting(db.Model):
    __tablename__ = "meetings"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    title = db.Column(db.String(200), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.BigInteger)  # bytes

    # Processing
    status = db.Column(db.String(20), nullable=False, default="pending")
    # pending | processing | transcribing | summarizing | completed | failed
    task_id = db.Column(db.String(255), index=True)
    progress = db.Column(db.Integer, default=0)  # 0-100
    error_message = db.Column(db.Text)

    # Results
    transcript = db.Column(db.Text)
    minutes_of_meeting = db.Column(db.Text)

    # Metadata
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)

    # Demo / guest sessions
    is_demo = db.Column(db.Boolean, nullable=False, default=False)
    session_token = db.Column(db.String(64), nullable=True, index=True)

    def __repr__(self) -> str:
        return f"<Meeting {self.id}: {self.title} [{self.status}]>"


class SystemConfig(db.Model):
    __tablename__ = "system_config"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.Text)
    description = db.Column(db.String(255))
    is_sensitive = db.Column(db.Boolean, default=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    @classmethod
    def get(cls, key: str, default=None):
        row = cls.query.filter_by(key=key).first()
        if row and row.value is not None:
            return row.value
        return default

    @classmethod
    def set(cls, key: str, value, description: str = None, is_sensitive: bool = False, updated_by: int = None):
        row = cls.query.filter_by(key=key).first()
        if row:
            row.value = str(value) if value is not None else None
            row.updated_at = datetime.now(timezone.utc)
            if updated_by:
                row.updated_by = updated_by
        else:
            row = cls(
                key=key,
                value=str(value) if value is not None else None,
                description=description,
                is_sensitive=is_sensitive,
                updated_by=updated_by,
            )
            db.session.add(row)
        db.session.commit()

    def __repr__(self) -> str:
        return f"<SystemConfig {self.key}>"
