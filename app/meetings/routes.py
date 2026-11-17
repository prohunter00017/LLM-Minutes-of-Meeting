import os
import uuid
from datetime import datetime, timezone, timedelta
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app,
    abort,
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models import Meeting, SystemConfig
from app.utils.plan_limits import check_upload_quota, increment_upload_usage, get_plan_retention_days

meetings_bp = Blueprint("meetings", __name__, url_prefix="/meetings")

ALLOWED_EXTENSIONS = {"mp4", "mp3", "wav", "m4a", "webm", "ogg", "mkv"}


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@meetings_bp.route("/")
@login_required
def list_meetings():
    page = request.args.get("page", 1, type=int)
    status_filter = request.args.get("status", "")

    q = Meeting.query.filter_by(user_id=current_user.id)
    if status_filter:
        q = q.filter_by(status=status_filter)

    meetings = q.order_by(Meeting.created_at.desc()).paginate(
        page=page, per_page=15, error_out=False
    )
    return render_template(
        "meetings/list.html", meetings=meetings, status_filter=status_filter
    )


@meetings_bp.route("/record")
@login_required
def record():
    return render_template("meetings/record.html")


@meetings_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        # Quota check
        allowed, msg, uploads_used, uploads_limit = check_upload_quota(current_user)
        if not allowed:
            flash(msg, "error")
            return redirect(url_for("billing.index"))

        if "file" not in request.files:
            flash("No file selected.", "error")
            return redirect(request.url)

        file = request.files["file"]
        if not file or file.filename == "":
            flash("No file selected.", "error")
            return redirect(request.url)

        if not _allowed_file(file.filename):
            flash("File type not supported. Allowed: mp4, mp3, wav, m4a, webm, ogg, mkv", "error")
            return redirect(request.url)

        title = request.form.get("title", "").strip()
        if not title:
            title = os.path.splitext(secure_filename(file.filename))[0]

        original_filename = secure_filename(file.filename)
        ext = original_filename.rsplit(".", 1)[1].lower()
        stored_filename = f"{uuid.uuid4().hex}.{ext}"

        upload_folder = current_app.config["UPLOAD_FOLDER"]
        file_path = os.path.join(upload_folder, stored_filename)
        file.save(file_path)
        file_size = os.path.getsize(file_path)

        retention_days = get_plan_retention_days(current_user)
        expires_at = datetime.now(timezone.utc) + timedelta(days=retention_days)

        meeting = Meeting(
            user_id=current_user.id,
            title=title,
            original_filename=original_filename,
            stored_filename=stored_filename,
            file_size=file_size,
            status="pending",
            expires_at=expires_at,
        )
        db.session.add(meeting)
        db.session.commit()

        # Enqueue Celery task
        from app.tasks.process import process_meeting
        task = process_meeting.delay(meeting.id)
        meeting.task_id = task.id
        meeting.status = "processing"
        db.session.commit()

        increment_upload_usage(current_user)
        db.session.commit()

        flash(f'Meeting "{title}" uploaded and queued for processing.', "success")
        return redirect(url_for("meetings.detail", meeting_id=meeting.id))

    return render_template("meetings/upload.html")


@meetings_bp.route("/<int:meeting_id>")
@login_required
def detail(meeting_id: int):
    meeting = Meeting.query.filter_by(
        id=meeting_id, user_id=current_user.id
    ).first_or_404()
    return render_template("meetings/detail.html", meeting=meeting)


@meetings_bp.route("/<int:meeting_id>/delete", methods=["POST"])
@login_required
def delete(meeting_id: int):
    meeting = Meeting.query.filter_by(
        id=meeting_id, user_id=current_user.id
    ).first_or_404()

    # Remove file from disk
    file_path = os.path.join(
        current_app.config["UPLOAD_FOLDER"], meeting.stored_filename
    )
    if os.path.exists(file_path):
        os.remove(file_path)

    db.session.delete(meeting)
    db.session.commit()
    flash("Meeting deleted.", "success")
    return redirect(url_for("meetings.list_meetings"))
