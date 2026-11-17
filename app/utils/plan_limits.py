"""Plan quota enforcement helpers."""
from datetime import datetime, timezone
from flask import current_app


PLAN_CONFIG = {
    "free": {"monthly_uploads": 5, "retention_days": 7},
    "starter": {"monthly_uploads": 25, "retention_days": 30},
    "pro": {"monthly_uploads": 200, "retention_days": 90},
}


def _maybe_reset_period(user):
    """Reset uploads counter if a new month has started."""
    now = datetime.now(timezone.utc)
    if user.plan_period_start is None:
        user.plan_period_start = now
        user.plan_uploads_used = 0
        return True

    # Check if we're in a new month compared to period_start
    ps = user.plan_period_start
    if now.year != ps.year or now.month != ps.month:
        user.plan_period_start = now
        user.plan_uploads_used = 0
        return True
    return False


def check_upload_quota(user) -> tuple:
    """
    Check if the user can upload/record another meeting.
    Returns (allowed: bool, message: str, uploads_used: int, uploads_limit: int)
    """
    # Admin always has unlimited access
    if getattr(user, "role", None) == "admin":
        return True, "", 0, -1

    _maybe_reset_period(user)

    plan_info = PLAN_CONFIG.get(user.plan, PLAN_CONFIG["free"])
    limit = plan_info["monthly_uploads"]

    if user.subscription_status == "canceled":
        # After cancellation, treat as free until period ends, then downgrade
        pass

    if limit == -1 or user.plan_uploads_used < limit:
        return True, "", user.plan_uploads_used, limit

    next_label = "Starter" if user.plan == "free" else "Pro"
    return (
        False,
        f"You've used all {limit} uploads on your {user.plan.capitalize()} plan. "
        f"Upgrade to {next_label} for more.",
        user.plan_uploads_used,
        limit,
    )


def increment_upload_usage(user):
    """Increment the user's monthly upload counter. Call after successful save."""
    # Admin usage is not tracked
    if getattr(user, "role", None) == "admin":
        return
    _maybe_reset_period(user)
    user.plan_uploads_used += 1


def get_plan_retention_days(user) -> int:
    """Return retention days for the user's current plan."""
    plan_info = PLAN_CONFIG.get(user.plan, PLAN_CONFIG["free"])
    return plan_info["retention_days"]


def get_plan_info(user):
    """Return full plan info dict for the user."""
    # Admin always shows unlimited
    if getattr(user, "role", None) == "admin":
        return {
            "plan": "admin",
            "monthly_uploads": -1,
            "uploads_used": 0,
            "status": "active",
            "retention_days": 9999,
            "price_cents": 0,
            "label": "Admin",
        }
    _maybe_reset_period(user)
    plan_info = PLAN_CONFIG.get(user.plan, PLAN_CONFIG["free"]).copy()
    plan_info["plan"] = user.plan
    plan_info["uploads_used"] = user.plan_uploads_used
    plan_info["status"] = user.subscription_status
    return plan_info
