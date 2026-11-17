from flask import Blueprint, render_template, current_app

legal_bp = Blueprint("legal", __name__, url_prefix="/legal")


@legal_bp.route("/privacy")
def privacy():
    return render_template("legal/privacy.html")


@legal_bp.route("/terms")
def terms():
    return render_template("legal/terms.html")


@legal_bp.route("/contact")
def contact():
    return render_template(
        "legal/contact.html",
        contact_name=current_app.config.get("CONTACT_NAME", ""),
        contact_email=current_app.config.get("CONTACT_EMAIL", ""),
    )
