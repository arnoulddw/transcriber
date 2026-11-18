import logging
from functools import wraps

from flask import Blueprint, current_app, jsonify, request
from flask_babel import gettext as _
from flask_login import current_user, login_required

from app.core.decorators import has_live_access
from app.extensions import build_user_limit_key, limiter
from app.services import live_transcription_service
from app.services.live_transcription_service import (
    LiveTranscriptionPermissionError,
    LiveTranscriptionUpstreamError,
    LiveTranscriptionValidationError,
)
from app.services.user_service import MissingApiKeyError


live_bp = Blueprint("live", __name__, url_prefix="/api/live")
LOGGER = logging.getLogger(__name__)


def live_permission_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not has_live_access(current_user):
            return jsonify({"error": _("You do not have access to Live transcription.")}), 403
        return view(*args, **kwargs)

    return wrapped


@live_bp.route("/session", methods=["POST"])
@live_permission_required
@limiter.limit("10 per minute", key_func=lambda: build_user_limit_key("live-session"))
def create_live_session():
    data = request.get_json(silent=True) or {}
    try:
        result = live_transcription_service.create_session(
            current_user,
            data.get("sdp"),
            data.get("language_code", "auto"),
            data.get("context_prompt", ""),
            data.get("model"),
        )
        return jsonify(result)
    except LiveTranscriptionValidationError as exc:
        return jsonify({"error": _(str(exc))}), 400
    except (LiveTranscriptionPermissionError, MissingApiKeyError) as exc:
        return jsonify({"error": _(str(exc))}), 403
    except LiveTranscriptionUpstreamError as exc:
        return jsonify({"error": _(str(exc))}), 502
    except Exception:
        LOGGER.exception("Unexpected error while creating a live transcription session.")
        return jsonify({"error": _("Could not start Live transcription.")}), 500


@live_bp.route("/session/refresh", methods=["POST"])
@live_permission_required
@limiter.limit("10 per minute", key_func=lambda: build_user_limit_key("live-session-refresh"))
def refresh_live_session():
    data = request.get_json(silent=True) or {}
    try:
        result = live_transcription_service.refresh_session_token(
            current_user,
            data.get("session_token"),
        )
        return jsonify(result)
    except LiveTranscriptionValidationError as exc:
        return jsonify({"error": _(str(exc))}), 400
    except (LiveTranscriptionPermissionError, MissingApiKeyError) as exc:
        return jsonify({"error": _(str(exc))}), 403
    except LiveTranscriptionUpstreamError as exc:
        return jsonify({"error": _(str(exc))}), 502
    except Exception:
        LOGGER.exception("Unexpected error while refreshing a live transcription session.")
        return jsonify({"error": _("Could not refresh Live transcription.")}), 500


@live_bp.route("/chunk", methods=["POST"])
@live_permission_required
@limiter.limit("30 per minute", key_func=lambda: build_user_limit_key("live-chunk"))
def transcribe_live_chunk():
    data = request.get_json(silent=True) or {}
    try:
        sequence = data.get("sequence", 0)
        if not isinstance(sequence, int) or sequence < 0:
            return jsonify({"error": _("The live audio sequence is invalid.")}), 400
        result = live_transcription_service.transcribe_openrouter_chunk(
            current_user,
            data.get("session_token"),  # type: ignore[arg-type]
            data.get("audio_data"),  # type: ignore[arg-type]
            data.get("audio_format", "wav"),
            sequence,
        )
        return jsonify(result)
    except LiveTranscriptionValidationError as exc:
        return jsonify({"error": _(str(exc))}), 400
    except (LiveTranscriptionPermissionError, MissingApiKeyError) as exc:
        return jsonify({"error": _(str(exc))}), 403
    except LiveTranscriptionUpstreamError as exc:
        return jsonify({"error": _(str(exc))}), 502
    except Exception:
        LOGGER.exception("Unexpected error while transcribing an OpenRouter live chunk.")
        return jsonify({"error": _("Could not transcribe the Live audio chunk.")}), 500


@live_bp.route("/finalize", methods=["POST"])
@live_permission_required
def finalize_live_session():
    data = request.get_json(silent=True) or {}
    try:
        result = live_transcription_service.finalize_session(
            current_user,
            data.get("session_token"),
            data.get("transcript"),
            detected_language=data.get("detected_language"),
        )
        result["history_url"] = "/"
        return jsonify(result)
    except LiveTranscriptionValidationError as exc:
        return jsonify({"error": _(str(exc))}), 400
    except LiveTranscriptionPermissionError as exc:
        return jsonify({"error": _(str(exc))}), 403
    except Exception:
        LOGGER.exception("Unexpected error while saving a live transcription.")
        return jsonify({"error": _("Could not save the Live transcript.")}), 500


@live_bp.route("/stop", methods=["POST"])
@live_permission_required
def stop_live_session():
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(
            live_transcription_service.hangup_session(
                current_user,
                data.get("session_token"),
            )
        )
    except LiveTranscriptionValidationError as exc:
        return jsonify({"error": _(str(exc))}), 400
    except (LiveTranscriptionPermissionError, MissingApiKeyError) as exc:
        return jsonify({"error": _(str(exc))}), 403
    except LiveTranscriptionUpstreamError as exc:
        return jsonify({"error": _(str(exc))}), 502
    except Exception:
        LOGGER.exception("Unexpected error while stopping a live transcription.")
        return jsonify({"error": _("Could not stop the Live transcription.")}), 500
