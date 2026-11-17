"""Periodic billing/plan tasks."""
import logging
from datetime import datetime, timezone
from app.extensions import celery, db
from app.models import User
from app.utils.plan_limits import _maybe_reset_period

logger = logging.getLogger(__name__)


@celery.task(name="app.tasks.billing.reset_monthly_uploads")
def reset_monthly_uploads() -> dict:
    """
    Runs daily. Resets plan_uploads_used for any user whose plan_period_start
    is in a previous month relative to now.
    """
    now = datetime.now(timezone.utc)
    users = User.query.all()
    reset_count = 0

    for user in users:
        ps = user.plan_period_start
        if ps is None or now.year != ps.year or now.month != ps.month:
            user.plan_period_start = now
            user.plan_uploads_used = 0
            reset_count += 1

    if reset_count:
        db.session.commit()
        logger.info("Reset monthly uploads for %d user(s)", reset_count)

    return {"reset": reset_count}
