import os
import secrets
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
    jsonify,
    abort,
    session,
)
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models import Meeting, SystemConfig

demo_bp = Blueprint("demo", __name__, url_prefix="/demo")

ALLOWED_EXTENSIONS = {"mp4", "mp3", "wav", "m4a", "webm", "ogg", "mkv"}
MAX_DEMO_PER_SESSION = 3


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _get_demo_tokens():
    return session.get("demo_tokens", [])


def _add_demo_token(token: str):
    tokens = _get_demo_tokens()
    if token not in tokens:
        tokens.append(token)
        session["demo_tokens"] = tokens
        session.modified = True


@demo_bp.route("/")
def index():
    demo_count = len(_get_demo_tokens())
    return render_template("demo.html", demo_count=demo_count, max_demos=MAX_DEMO_PER_SESSION)


@demo_bp.route("/upload", methods=["POST"])
def upload():
    tokens = _get_demo_tokens()
    if len(tokens) >= MAX_DEMO_PER_SESSION:
        flash(
            "Demo limit reached (3 per session). Sign up for free to upload more meetings.",
            "error",
        )
        return redirect(url_for("demo.index"))

    if "file" not in request.files:
        flash("No file selected.", "error")
        return redirect(url_for("demo.index"))

    file = request.files["file"]
    if not file or file.filename == "":
        flash("No file selected.", "error")
        return redirect(url_for("demo.index"))

    if not _allowed_file(file.filename):
        flash(
            "File type not supported. Allowed: mp4, mp3, wav, m4a, webm, ogg, mkv",
            "error",
        )
        return redirect(url_for("demo.index"))

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

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    meeting = Meeting(
        user_id=None,
        title=title,
        original_filename=original_filename,
        stored_filename=stored_filename,
        file_size=file_size,
        status="pending",
        expires_at=expires_at,
        is_demo=True,
        session_token=token,
    )
    db.session.add(meeting)
    db.session.commit()

    _add_demo_token(token)

    # Enqueue Celery task
    from app.tasks.process import process_meeting
    task = process_meeting.delay(meeting.id)
    meeting.task_id = task.id
    meeting.status = "processing"
    db.session.commit()

    flash(f'Meeting "{title}" uploaded and queued for processing.', "success")
    return redirect(url_for("demo.result", token=token))


@demo_bp.route("/record", methods=["POST"])
def record():
    tokens = _get_demo_tokens()
    if len(tokens) >= MAX_DEMO_PER_SESSION:
        return jsonify({"error": "Demo limit reached (3 per session). Sign up for free to record more meetings."}), 429

    if "audio" not in request.files:
        return jsonify({"error": "No audio data received."}), 400

    audio = request.files["audio"]
    if not audio or audio.filename == "":
        return jsonify({"error": "No audio data received."}), 400

    title = request.form.get("title", "").strip() or "Recorded Meeting"
    original_filename = "recording.webm"
    stored_filename = f"{uuid.uuid4().hex}.webm"

    upload_folder = current_app.config["UPLOAD_FOLDER"]
    file_path = os.path.join(upload_folder, stored_filename)
    audio.save(file_path)
    file_size = os.path.getsize(file_path)

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    meeting = Meeting(
        user_id=None,
        title=title,
        original_filename=original_filename,
        stored_filename=stored_filename,
        file_size=file_size,
        status="pending",
        expires_at=expires_at,
        is_demo=True,
        session_token=token,
    )
    db.session.add(meeting)
    db.session.commit()

    _add_demo_token(token)

    # Enqueue Celery task
    from app.tasks.process import process_meeting
    task = process_meeting.delay(meeting.id)
    meeting.task_id = task.id
    meeting.status = "processing"
    db.session.commit()

    return jsonify({"token": token, "status": "processing"}), 201


@demo_bp.route("/status/<token>")
def status(token: str):
    meeting = Meeting.query.filter_by(session_token=token, is_demo=True).first()
    if not meeting:
        abort(404)
    return jsonify(
        {
            "id": meeting.id,
            "status": meeting.status,
            "progress": meeting.progress,
            "error_message": meeting.error_message,
            "has_transcript": bool(meeting.transcript),
            "has_minutes": bool(meeting.minutes_of_meeting),
        }
    )


@demo_bp.route("/result/<token>")
def result(token: str):
    meeting = Meeting.query.filter_by(session_token=token, is_demo=True).first_or_404()
    return render_template("demo_result.html", meeting=meeting)
