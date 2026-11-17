from flask import Blueprint, jsonify, abort, request
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Meeting

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")


@api_bp.route("/meetings/<int:meeting_id>/status")
@login_required
def meeting_status(meeting_id: int):
    meeting = Meeting.query.filter_by(
        id=meeting_id, user_id=current_user.id
    ).first()
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


@api_bp.route("/meetings")
@login_required
def meetings_list():
    meetings = (
        Meeting.query.filter_by(user_id=current_user.id)
        .order_by(Meeting.created_at.desc())
        .limit(50)
        .all()
    )
    return jsonify(
        [
            {
                "id": m.id,
                "title": m.title,
                "status": m.status,
                "progress": m.progress,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in meetings
        ]
    )


@api_bp.route("/recordings", methods=["POST"])
@login_required
def create_recording():
    """Receive an audio blob from the browser recorder and enqueue processing."""
    import os
    import uuid
    from datetime import datetime, timezone, timedelta
    from flask import current_app
    from app.models import SystemConfig
    from app.tasks.process import process_meeting

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

    retention_days = int(SystemConfig.get("meeting_retention_days", "30"))
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

    task = process_meeting.delay(meeting.id)
    meeting.task_id = task.id
    meeting.status = "processing"
    db.session.commit()

    return jsonify({"meeting_id": meeting.id, "status": "processing"}), 201


@api_bp.route("/quota")
@login_required
def quota():
    from app.utils.plan_limits import get_plan_info
    info = get_plan_info(current_user)
    return jsonify(info)
