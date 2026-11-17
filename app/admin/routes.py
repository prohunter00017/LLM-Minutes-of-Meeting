from functools import wraps
import csv
import io
import json
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, Response, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models import User, SystemConfig

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


@admin_bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    if request.method == "POST":
        tab = request.form.get("tab", "llm")

        if tab == "llm":
            SystemConfig.set("llm_base_url", request.form.get("llm_base_url", ""), updated_by=current_user.id)
            SystemConfig.set("llm_model", request.form.get("llm_model", ""), updated_by=current_user.id)
            api_key = request.form.get("llm_api_key", "")
            if api_key and api_key != "••••••••":
                SystemConfig.set("llm_api_key", api_key, is_sensitive=True, updated_by=current_user.id)

        elif tab == "speech":
            SystemConfig.set("speech_provider", request.form.get("speech_provider", "deepgram"), updated_by=current_user.id)
            for provider in ["deepgram", "assemblyai", "sarvam", "elevenlabs"]:
                key_val = request.form.get(f"{provider}_api_key", "")
                if key_val and key_val != "••••••••":
                    SystemConfig.set(f"{provider}_api_key", key_val, is_sensitive=True, updated_by=current_user.id)

        elif tab == "storage":
            retention = request.form.get("meeting_retention_days", "30")
            try:
                retention = max(1, int(retention))
            except ValueError:
                retention = 30
            SystemConfig.set("meeting_retention_days", str(retention), updated_by=current_user.id)

        flash("Settings saved.", "success")
        if request.form.get("redirect_to") == "api_keys":
            return redirect(url_for("admin.api_keys"))
        return redirect(url_for("admin.settings", tab=tab))

    tab = request.args.get("tab", "llm")
    config = {row.key: row for row in SystemConfig.query.all()}
    return render_template("admin/settings.html", config=config, active_tab=tab)


@admin_bp.route("/api-keys")
@admin_required
def api_keys():
    """Admin-only page for LLM and speech API credentials (same forms as Settings tabs)."""
    config = {row.key: row for row in SystemConfig.query.all()}
    return render_template("admin/api_keys.html", config=config)


@admin_bp.route("/api-keys/health")
@admin_required
def api_keys_health():
    """Live-check every configured API credential. Returns JSON status per provider."""
    import httpx

    results = []

    # ── LLM ────────────────────────────────────────────────────────────
    llm_key = SystemConfig.get("llm_api_key", "") or ""
    llm_model = SystemConfig.get("llm_model", "") or ""
    llm_base = SystemConfig.get("llm_base_url", "") or ""

    if not llm_key:
        results.append({"name": "LLM (Cloudflare)", "status": "missing", "detail": "No API key configured"})
    else:
        try:
            if "cloudflare.com" in llm_base:
                acct = ""
                parts = llm_base.split("/")
                for i, p in enumerate(parts):
                    if p == "accounts" and i + 1 < len(parts):
                        acct = parts[i + 1]
                        break
                url = f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{llm_model}"
                payload = {"messages": [{"role": "user", "content": "ping"}], "max_tokens": 5}
            else:
                url = llm_base.rstrip("/") + "/chat/completions"
                payload = {"model": llm_model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5}
            with httpx.Client(timeout=45) as c:
                r = c.post(url, headers={"Authorization": f"Bearer {llm_key}",
                                        "Content-Type": "application/json"}, json=payload)
            if r.status_code == 200:
                results.append({"name": f"LLM ({llm_model})", "status": "ok", "detail": "Operational"})
            else:
                results.append({"name": f"LLM ({llm_model})", "status": "error",
                                "detail": f"HTTP {r.status_code}: {r.text[:180]}"})
        except Exception as exc:
            results.append({"name": f"LLM ({llm_model})", "status": "error", "detail": str(exc)[:200]})

    # ── Speech-to-text ─────────────────────────────────────────────────
    provider = SystemConfig.get("speech_provider", "deepgram") or "deepgram"
    speech_checks = {
        "elevenlabs": ("ElevenLabs", "https://api.elevenlabs.io/v1/user/subscription", "xi-api-key"),
        "deepgram": ("Deepgram", "https://api.deepgram.com/v1/projects", "Authorization"),
        "assemblyai": ("AssemblyAI", "https://api.assemblyai.com/v2/subscription", "authorization"),
        "sarvam": ("Sarvam AI", "https://api.sarvam.ai/health", "api-key"),
    }
    label, url, header = speech_checks.get(provider, (provider, "", ""))
    key = SystemConfig.get(f"{provider}_api_key", "") or ""

    if not label:
        results.append({"name": f"STT ({provider})", "status": "error", "detail": f"Unknown provider '{provider}'"})
    elif not key:
        results.append({"name": f"STT ({label})", "status": "missing", "detail": f"No API key for active provider '{provider}'"})
    else:
        try:
            hdrs = {header: key}
            if header == "Authorization":
                hdrs = {"Authorization": f"Token {key}"}
            with httpx.Client(timeout=45) as c:
                r = c.get(url, headers=hdrs)
            if r.status_code in (200, 201):
                results.append({"name": f"STT ({label})", "status": "ok", "detail": "Operational"})
            else:
                results.append({"name": f"STT ({label})", "status": "error",
                                "detail": f"HTTP {r.status_code}: {r.text[:180]}"})
        except Exception as exc:
            results.append({"name": f"STT ({label})", "status": "error", "detail": str(exc)[:200]})

    # ── Stripe ────────────────────────────────────────────────────────
    stripe_key = current_app.config.get("STRIPE_SECRET_KEY", "") or ""
    if not stripe_key:
        results.append({"name": "Stripe", "status": "missing", "detail": "No Stripe secret key"})
    else:
        try:
            import stripe as stripe_sdk
            stripe_sdk.api_key = stripe_key
            balance = stripe_sdk.Balance.retrieve()
            live = stripe_key.startswith("sk_live_")
            # Stripe returns a Balance object, not a dict — convert before indexing.
            if hasattr(balance, "to_dict"):
                balance = balance.to_dict()
            available = balance.get("available") or [{}]
            amount = available[0].get("amount", 0)
            currency = available[0].get("currency", "").upper()
            results.append({"name": "Stripe", "status": "ok",
                            "detail": f"{'Live' if live else 'Test'} mode, available {amount / 100:.2f} {currency}".strip()})
        except Exception as exc:
            results.append({"name": "Stripe", "status": "error", "detail": str(exc)[:200]})

    if request.args.get("format") == "json":
        return json.dumps(results, indent=2)

    return render_template("admin/api_health.html", results=results)


@admin_bp.route("/users")
@admin_required
def users():
    all_users = User.query.order_by(User.created_at.desc()).all()

    chart_data = {
        "total": len(all_users),
        "free": sum(1 for u in all_users if u.plan == "free"),
        "starter": sum(1 for u in all_users if u.plan == "starter"),
        "pro": sum(1 for u in all_users if u.plan == "pro"),
        "active": sum(1 for u in all_users if u.is_active),
        "inactive": sum(1 for u in all_users if not u.is_active),
        "monthly": sum(1 for u in all_users if not u.plan_is_annual and u.plan != "free"),
        "yearly": sum(1 for u in all_users if u.plan_is_annual),
        "companies": set(u.email.split("@")[1] for u in all_users if u.plan != "free" and "@" in u.email),
    }

    return render_template("admin/users.html", users=all_users, chart_data=chart_data)


@admin_bp.route("/users/create", methods=["POST"])
@admin_required
def create_user():
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    role = request.form.get("role", "user")

    if not username or not email or not password:
        flash("Username, email, and password are required.", "error")
        return redirect(url_for("admin.users"))

    if User.query.filter_by(username=username).first():
        flash(f'Username "{username}" is already taken.', "error")
        return redirect(url_for("admin.users"))

    if User.query.filter_by(email=email).first():
        flash(f'Email "{email}" is already in use.', "error")
        return redirect(url_for("admin.users"))

    user = User(username=username, email=email, role=role, is_active=True)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    flash(f'User "{username}" created successfully.', "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def toggle_user(user_id: int):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    if user.id == current_user.id:
        flash("You cannot deactivate your own account.", "error")
        return redirect(url_for("admin.users"))
    user.is_active = not user.is_active
    db.session.commit()
    status = "activated" if user.is_active else "deactivated"
    flash(f'User "{user.username}" {status}.', "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/role", methods=["POST"])
@admin_required
def change_role(user_id: int):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    if user.id == current_user.id:
        flash("You cannot change your own role.", "error")
        return redirect(url_for("admin.users"))
    new_role = request.form.get("role", "user")
    if new_role not in ("admin", "user"):
        flash("Invalid role.", "error")
        return redirect(url_for("admin.users"))
    user.role = new_role
    db.session.commit()
    flash(f'Role for "{user.username}" changed to {new_role}.', "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id: int):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    if user.id == current_user.id:
        flash("You cannot delete your own account.", "error")
        return redirect(url_for("admin.users"))
    db.session.delete(user)
    db.session.commit()
    flash(f'User "{user.username}" deleted.', "success")
    return redirect(url_for("admin.users"))


# ═══════════════════════════════════════════════════════════════════════
#  Subscriptions
# ═══════════════════════════════════════════════════════════════════════

@admin_bp.route("/subscriptions")
@admin_required
def subscriptions():
    """Admin subscription dashboard: view & manage all user plans."""
    all_users = User.query.order_by(User.created_at.desc()).all()

    mrr = 0
    for u in all_users:
        if u.subscription_status != "active":
            continue
        if u.plan == "starter":
            mrr += 90 / 12 if u.plan_is_annual else 9
        elif u.plan == "pro":
            mrr += 290 / 12 if u.plan_is_annual else 29

    stats = {
        "total": len(all_users),
        "free": sum(1 for u in all_users if u.plan == "free"),
        "starter": sum(1 for u in all_users if u.plan == "starter"),
        "pro": sum(1 for u in all_users if u.plan == "pro"),
        "mrr": round(mrr),
        "mrr_monthly": sum(
            29 if u.plan == "pro" else 9
            for u in all_users
            if u.subscription_status == "active" and u.plan != "free" and not u.plan_is_annual
        ),
        "mrr_yearly_amortized": round(sum(
            290 / 12 if u.plan == "pro" else 90 / 12
            for u in all_users
            if u.subscription_status == "active" and u.plan_is_annual
        )),
        "yearly_subs": sum(1 for u in all_users if u.plan_is_annual),
        "monthly_subs": sum(1 for u in all_users if not u.plan_is_annual and u.plan != "free"),
        "active_paid": sum(1 for u in all_users if u.plan != "free" and u.subscription_status == "active"),
    }

    return render_template("admin/subscriptions.html", users=all_users, stats=stats)


@admin_bp.route("/subscriptions/<int:user_id>/set-plan", methods=["POST"])
@admin_required
def set_user_plan(user_id: int):
    """Set a user's plan directly (bypass Stripe — for crypto/offline payments)."""
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    if user.id == current_user.id:
        flash("You cannot change your own plan here.", "error")
        return redirect(url_for("admin.subscriptions"))

    new_plan = request.form.get("plan", "free")
    if new_plan not in ("free", "starter", "pro"):
        flash("Invalid plan.", "error")
        return redirect(url_for("admin.subscriptions"))

    # If downgrading to free and they have a Stripe subscription, cancel it first
    if new_plan == "free" and user.stripe_subscription_id:
        try:
            from app.billing.stripe_client import cancel_subscription_at_period_end
            cancel_subscription_at_period_end(user.stripe_subscription_id)
            flash(f"Stripe subscription for {user.username} was cancelled.", "info")
        except Exception as exc:
            flash(f"Could not cancel Stripe subscription: {exc}", "error")
            return redirect(url_for("admin.subscriptions"))

    user.plan = new_plan
    user.subscription_status = "active" if new_plan != "free" else "active"
    if new_plan == "free":
        user.stripe_price_id = None
        user.plan_is_annual = False
    db.session.commit()

    flash(f'Plan for "{user.username}" set to {new_plan.capitalize()}.', "success")
    return redirect(url_for("admin.subscriptions"))


@admin_bp.route("/subscriptions/<int:user_id>/reset-uploads", methods=["POST"])
@admin_required
def reset_user_uploads(user_id: int):
    """Reset a user's monthly upload counter."""
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    user.plan_uploads_used = 0
    db.session.commit()
    flash(f'Upload counter reset for "{user.username}".', "success")
    return redirect(url_for("admin.subscriptions"))


@admin_bp.route("/subscriptions/<int:user_id>/cancel", methods=["POST"])
@admin_required
def cancel_user_subscription(user_id: int):
    """Cancel a user's Stripe subscription and downgrade to Free."""
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    if user.id == current_user.id:
        flash("You cannot cancel your own subscription here.", "error")
        return redirect(url_for("admin.subscriptions"))

    if not user.stripe_subscription_id:
        flash(f"{user.username} has no active Stripe subscription.", "error")
        return redirect(url_for("admin.subscriptions"))

    try:
        from app.billing.stripe_client import cancel_subscription_at_period_end
        cancel_subscription_at_period_end(user.stripe_subscription_id)
        user.subscription_status = "canceled"
        db.session.commit()
        flash(f'Subscription for "{user.username}" will cancel at period end.', "success")
    except Exception as exc:
        flash(f"Could not cancel subscription: {exc}", "error")

    return redirect(url_for("admin.subscriptions"))


@admin_bp.route("/subscriptions/<int:user_id>/delete-sub", methods=["POST"])
@admin_required
def delete_user_subscription(user_id: int):
    """Hard-remove all Stripe fields and downgrade user to Free immediately."""
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    if user.id == current_user.id:
        flash("You cannot delete your own subscription here.", "error")
        return redirect(url_for("admin.subscriptions"))

    # Try to cancel on Stripe if a sub exists
    if user.stripe_subscription_id:
        try:
            from app.billing.stripe_client import cancel_subscription_at_period_end
            cancel_subscription_at_period_end(user.stripe_subscription_id)
        except Exception:
            pass  # swallow — we're wiping locally regardless

    user.plan = "free"
    user.subscription_status = "active"
    user.stripe_subscription_id = None
    user.stripe_price_id = None
    user.stripe_customer_id = None
    user.plan_is_annual = False
    user.plan_uploads_used = 0
    db.session.commit()

    flash(f'Subscription data wiped for "{user.username}". Downgraded to Free.', "success")
    return redirect(url_for("admin.subscriptions"))


# ═══════════════════════════════════════════════════════════════════════
#  Export (CSV / JSON)
# ═══════════════════════════════════════════════════════════════════════

@admin_bp.route("/users/export/csv")
@admin_required
def export_users_csv():
    all_users = User.query.order_by(User.created_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Username", "Email", "Role", "Plan", "Billing",
                     "Status", "Uploads Used", "Stripe Customer", "Stripe Subscription",
                     "Joined"])
    for u in all_users:
        writer.writerow([
            u.id, u.username, u.email, u.role, u.plan,
            "yearly" if u.plan_is_annual else ("monthly" if u.plan != "free" else "—"),
            u.subscription_status, u.plan_uploads_used,
            u.stripe_customer_id or "", u.stripe_subscription_id or "",
            u.created_at.strftime("%Y-%m-%d") if u.created_at else "",
        ])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=users_export_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"},
    )


@admin_bp.route("/users/export/json")
@admin_required
def export_users_json():
    all_users = User.query.order_by(User.created_at.desc()).all()
    data = []
    for u in all_users:
        data.append({
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "role": u.role,
            "plan": u.plan,
            "billing": "yearly" if u.plan_is_annual else ("monthly" if u.plan != "free" else "—"),
            "subscription_status": u.subscription_status,
            "uploads_used": u.plan_uploads_used,
            "stripe_customer_id": u.stripe_customer_id,
            "stripe_subscription_id": u.stripe_subscription_id,
            "stripe_price_id": u.stripe_price_id,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        })
    return Response(
        json.dumps(data, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=users_export_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"},
    )
