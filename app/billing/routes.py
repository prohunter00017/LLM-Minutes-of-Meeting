"""Billing routes: subscriptions, checkout, Stripe webhooks."""
from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    request,
    flash,
    current_app,
    jsonify,
)
from flask_login import login_required, current_user
from app.extensions import db
from app.models import User
from app.utils.plan_limits import get_plan_info

billing_bp = Blueprint("billing", __name__, url_prefix="/billing")


# ── Helpers ──────────────────────────────────────────────────────

def _price_choices():
    cfg = current_app.config
    return {
        "starter_monthly": cfg.get("STRIPE_PRICE_STARTER_MONTHLY", ""),
        "starter_yearly": cfg.get("STRIPE_PRICE_STARTER_YEARLY", ""),
        "pro_monthly": cfg.get("STRIPE_PRICE_PRO_MONTHLY", ""),
        "pro_yearly": cfg.get("STRIPE_PRICE_PRO_YEARLY", ""),
    }


def _plan_for_price(price_id: str) -> str:
    prices = _price_choices()
    if price_id in (prices["starter_monthly"], prices["starter_yearly"]):
        return "starter"
    if price_id in (prices["pro_monthly"], prices["pro_yearly"]):
        return "pro"
    return "free"


def _is_annual_price(price_id: str) -> bool:
    prices = _price_choices()
    return price_id in (prices["starter_yearly"], prices["pro_yearly"])


# ── Dashboard ────────────────────────────────────────────────────

@billing_bp.route("/")
@login_required
def index():
    info = get_plan_info(current_user)
    return render_template("billing/index.html", plan_info=info)


# ── Checkout ─────────────────────────────────────────────────────

@billing_bp.route("/checkout", methods=["POST"])
@login_required
def checkout():
    plan = request.form.get("plan", "starter")
    billing_cycle = request.form.get("billing_cycle", "monthly")

    prices = _price_choices()
    price_key = f"{plan}_{billing_cycle}"
    price_id = prices.get(price_key, "")

    if not price_id:
        flash("Invalid plan selection.", "error")
        return redirect(url_for("billing.index"))

    try:
        from app.billing.stripe_client import create_customer, create_checkout_session

        # Ensure Stripe customer exists
        if not current_user.stripe_customer_id:
            customer = create_customer(current_user.email, current_user.username)
            current_user.stripe_customer_id = customer["id"]
            db.session.commit()

        success_url = request.url_root.rstrip("/") + url_for("billing.success") + "?session_id={CHECKOUT_SESSION_ID}"
        cancel_url = request.url_root.rstrip("/") + url_for("billing.cancel")

        session = create_checkout_session(
            current_user.stripe_customer_id,
            price_id,
            success_url,
            cancel_url,
        )
        return redirect(session["url"], code=303)

    except Exception as exc:
        import traceback
        current_app.logger.error("Stripe checkout failed: %s", exc)
        current_app.logger.error(traceback.format_exc())
        flash(f"Could not start checkout: {exc}", "error")
        return redirect(url_for("billing.index"))


# ── Success / Cancel ─────────────────────────────────────────────

@billing_bp.route("/success")
@login_required
def success():
    session_id = request.args.get("session_id")
    if not session_id:
        flash("Missing checkout session.", "error")
        return redirect(url_for("billing.index"))

    try:
        from app.billing.stripe_client import get_stripe
        s = get_stripe()
        session = s.checkout.Session.retrieve(session_id)
        subscription = s.Subscription.retrieve(session["subscription"])

        current_user.stripe_subscription_id = subscription["id"]
        current_user.stripe_price_id = subscription["items"]["data"][0]["price"]["id"]
        current_user.plan = _plan_for_price(current_user.stripe_price_id)
        current_user.plan_is_annual = _is_annual_price(current_user.stripe_price_id)
        current_user.subscription_status = "active"
        current_user.plan_period_start = datetime.now(timezone.utc)
        current_user.plan_uploads_used = 0
        db.session.commit()

        flash(f"Welcome to {current_user.plan.capitalize()}! Your subscription is active.", "success")
    except Exception as exc:
        flash(f"Could not confirm subscription: {exc}", "error")

    return redirect(url_for("billing.index"))


@billing_bp.route("/cancel")
@login_required
def cancel():
    flash("Checkout cancelled. No charges were made.", "info")
    return redirect(url_for("billing.index"))


# ── Cancel Subscription (graceful) ───────────────────────────────

@billing_bp.route("/cancel-subscription", methods=["POST"])
@login_required
def cancel_subscription():
    if not current_user.stripe_subscription_id:
        flash("No active subscription to cancel.", "error")
        return redirect(url_for("billing.index"))

    try:
        from app.billing.stripe_client import cancel_subscription_at_period_end
        cancel_subscription_at_period_end(current_user.stripe_subscription_id)
        current_user.subscription_status = "canceled"
        db.session.commit()
        flash("Your subscription will end at the close of the current billing period.", "success")
    except Exception as exc:
        flash(f"Could not cancel subscription: {exc}", "error")

    return redirect(url_for("billing.index"))


# ── Stripe Webhook ───────────────────────────────────────────────

@billing_bp.route("/webhooks/stripe", methods=["POST"])
def stripe_webhook():
    payload = request.get_data(as_text=False)
    sig_header = request.headers.get("Stripe-Signature", "")
    secret = current_app.config.get("STRIPE_WEBHOOK_SECRET", "")

    if not secret:
        return jsonify({"error": "Webhook secret not configured"}), 500

    try:
        from app.billing.stripe_client import construct_event
        event = construct_event(payload, sig_header, secret)
    except Exception:
        return jsonify({"error": "Invalid signature"}), 400

    event_type = event["type"]
    data_object = event["data"]["object"]

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(data_object)
    elif event_type == "invoice.payment_failed":
        _handle_payment_failed(data_object)
    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(data_object)

    return jsonify({"status": "ok"}), 200


def _handle_checkout_completed(session_obj):
    customer_id = session_obj.get("customer")
    subscription_id = session_obj.get("subscription")
    if not customer_id:
        return

    user = User.query.filter_by(stripe_customer_id=customer_id).first()
    if not user:
        return

    try:
        from app.billing.stripe_client import get_stripe
        s = get_stripe()
        subscription = s.Subscription.retrieve(subscription_id)
        price_id = subscription["items"]["data"][0]["price"]["id"]
        user.stripe_subscription_id = subscription_id
        user.stripe_price_id = price_id
        user.plan = _plan_for_price(price_id)
        user.plan_is_annual = _is_annual_price(price_id)
        user.subscription_status = "active"
        user.plan_period_start = datetime.now(timezone.utc)
        db.session.commit()
    except Exception:
        db.session.rollback()


def _handle_payment_failed(invoice_obj):
    customer_id = invoice_obj.get("customer")
    user = User.query.filter_by(stripe_customer_id=customer_id).first()
    if user:
        user.subscription_status = "past_due"
        db.session.commit()


def _handle_subscription_deleted(sub_obj):
    subscription_id = sub_obj.get("id")
    user = User.query.filter_by(stripe_subscription_id=subscription_id).first()
    if user:
        user.plan = "free"
        user.subscription_status = "canceled"
        user.stripe_subscription_id = None
        user.stripe_price_id = None
        user.plan_is_annual = False
        db.session.commit()


from datetime import datetime, timezone
