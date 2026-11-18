import base64
import binascii
import hashlib
import hmac
import json
import logging
import math
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx
from flask import current_app
from flask_babel import gettext as _
from itsdangerous import BadSignature, URLSafeSerializer

from app.core.decorators import check_permission
from app.core.utils import split_vocabulary_terms
from app.models import role as role_model
from app.models import live_session as live_session_model
from app.models import transcription as transcription_model
from app.models import transcription_catalog as transcription_catalog_model
from app.services import pricing_service, user_service
from app.services.openrouter import normalize_openrouter_model
from app.services.user_service import MissingApiKeyError
from app.tasks.background_queue import enqueue_title_generation
from app.services import access_service


LOGGER = logging.getLogger(__name__)
SESSION_TOKEN_SALT = "live-transcription-session-v1"
MAX_CONTEXT_WORDS = 120
MAX_TRANSCRIPT_CHARS = 10_000_000
MAX_SESSION_DURATION_MINUTES = 120
# Allow a small amount of clock skew while rejecting forged/future timestamps.
MAX_SESSION_CLOCK_SKEW_SECONDS = 5 * 60
# Minutes reserved against the role's live-minutes quota when a session starts.
LIVE_MINUTES_RESERVATION = 10.0
RETRYABLE_SESSION_STATUS_CODES = frozenset({502, 503, 504})
ENDED_CALL_STATUS_CODES = frozenset({404, 409})
MAX_OPENROUTER_CHUNK_BYTES = 8 * 1024 * 1024
GEMINI_WS_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained"
)
OPENROUTER_AUDIO_FORMATS = frozenset({"wav", "mp3", "flac", "m4a", "ogg", "webm", "aac"})
OPENROUTER_STT_MODELS = frozenset({
    "nvidia/nemotron-3.5-asr-streaming-multilingual-0.6b",
    "mistralai/voxtral-small-24b-2507-stt",
    "mistralai/voxtral-mini-3b-2507",
    "qwen/qwen3-asr-1.7b",
    "qwen/qwen3-asr-0.6b",
    "openai/gpt-transcribe",
    "openai/whisper-large-v3",
    "openai/whisper-large-v3-turbo",
    "openai/whisper-1",
    "openai/gpt-4o-transcribe",
})
LIVE_PROVIDER_PERMISSION_KEYS = {
    "openai": "use_api_openai",
    "gemini": "use_api_google_gemini",
    "openrouter": "use_api_openrouter",
}
LIVE_SESSION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def _load_genai():
    """Lazily import google-genai so non-Gemini installs pay no import cost."""
    global _genai_module
    if _genai_module is None:
        try:
            from google import genai as genai_module
        except Exception as exc:
            raise LiveTranscriptionUpstreamError(
                _("Could not connect to the live transcription service.")
            ) from exc
        _genai_module = genai_module
    return _genai_module


_genai_module: Optional[Any] = None


def _gemini_client(api_key: str):
    return _load_genai().Client(api_key=api_key)


def _configured_openrouter_stt_models() -> frozenset[str]:
    configured = current_app.config.get("OPENROUTER_LIVE_TRANSCRIPTION_MODELS", [])
    if isinstance(configured, str):
        configured = configured.split(",")
    return frozenset(
        str(model).strip()
        for model in configured
        if str(model).strip()
    )


def _resolve_openrouter_stt_models() -> frozenset[str]:
    """Return known and explicitly configured OpenRouter STT models."""
    return OPENROUTER_STT_MODELS | _configured_openrouter_stt_models()


class LiveTranscriptionError(Exception):
    """Base error for live transcription operations."""


class LiveTranscriptionValidationError(LiveTranscriptionError):
    """The user supplied invalid live transcription settings."""


class LiveTranscriptionPermissionError(LiveTranscriptionError):
    """The user cannot use a requested live transcription capability."""


class LiveTranscriptionUpstreamError(LiveTranscriptionError):
    """OpenAI could not create the realtime session."""


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt=SESSION_TOKEN_SALT)


def _resolve_live_model(user, requested: Optional[str] = None) -> str:
    configured = requested or getattr(user, "default_live_transcription_model", None)
    if not configured:
        configured = getattr(getattr(user, "role", None), "default_live_transcription_model", None)
    model_reference = str(
        configured or current_app.config.get("LIVE_TRANSCRIPTION_MODEL", "gpt-live-transcribe")
    ).strip()
    provider_hint, model = transcription_catalog_model.split_model_reference(model_reference)
    provider_config = current_app.config.get("LIVE_TRANSCRIPTION_PROVIDERS", {}) or {}
    allowed_models = {
        str(value).strip()
        for value in current_app.config.get("LIVE_TRANSCRIPTION_MODELS", [])
        if str(value).strip()
    }
    if user:
        try:
            key_status = user_service.get_effective_key_status(user)
            # Catalog-registered live models (normal + OpenRouter) are the
            # canonical source; retain bare codes for older saved settings.
            for entry in transcription_catalog_model.get_live_models(key_status):
                for candidate in (entry.get("model_key"), entry.get("code")):
                    candidate = str(candidate or "").strip()
                    if candidate:
                        allowed_models.add(candidate)
            for entry in (key_status.get("provider_keys", {}).get("openrouter", []) or []):
                purposes = entry.get("model_purposes", []) or []
                model_name = str(entry.get("model_slug") or entry.get("model_name") or "").strip()
                if "live" in purposes and model_name:
                    allowed_models.add(model_name)
        except Exception:
            LOGGER.debug("Could not add user-configured Live models.", exc_info=True)
    configured_provider = str(
        provider_config.get(model_reference) or provider_config.get(model) or ""
    ).strip().lower()
    is_openrouter_model = (
        provider_hint == "openrouter"
        or configured_provider == "openrouter"
        or "/" in model
    )
    if is_openrouter_model:
        allowed_models.update({model_reference, model})
    if not allowed_models:
        allowed_models.update({model_reference, model})
    if allowed_models and model_reference not in allowed_models and model not in allowed_models:
        raise LiveTranscriptionValidationError(_("The selected Live transcription model is not available."))
    provider = provider_hint or _resolve_provider(user, model)
    if provider == "openrouter":
        if model not in _resolve_openrouter_stt_models():
            raise LiveTranscriptionValidationError(
                _("The selected OpenRouter model is not listed as a transcription model.")
            )
        try:
            return normalize_openrouter_model(model)
        except ValueError as exc:
            raise LiveTranscriptionValidationError(_(str(exc))) from exc
    if not model or any(char.isspace() for char in model) or '/' in model:
        raise LiveTranscriptionValidationError(_("The selected Live transcription model is invalid."))
    return model


def _resolve_provider(user, model: str) -> str:
    configured = current_app.config.get('LIVE_TRANSCRIPTION_PROVIDERS', {}).get(model)
    if configured:
        return str(configured).strip().lower()
    if model.startswith("gemini-"):
        return "gemini"
    return "openrouter" if "/" in model else "openai"


def _ensure_live_provider_permission(user, provider: str, model: str) -> None:
    """Enforce the resolved provider permission after model selection."""
    permission_key = LIVE_PROVIDER_PERMISSION_KEYS.get(provider)
    if permission_key and not check_permission(user, permission_key):
        LOGGER.warning(
            "Live model permission denied for provider=%s model=%s permission=%s.",
            provider,
            model,
            permission_key,
        )
        raise LiveTranscriptionPermissionError(
            _("You do not have permission to use this transcription provider.")
        )


def _issue_session_token(
    user,
    transcription_id: str,
    started_at: float,
    language: str,
    prompt: str,
    model: str,
    provider: str,
    transport: str,
    **extra_fields: Any,
) -> str:
    """Persist a server-side session before returning its signed token."""
    session_id = uuid.uuid4().hex
    payload = {
        "session_id": session_id,
        "user_id": user.id,
        "transcription_id": transcription_id,
        "started_at": started_at,
        "language": language,
        "context_prompt_used": bool(prompt),
        "model": model,
        "provider": provider,
        "transport": transport,
        **extra_fields,
    }
    token = _serializer().dumps(payload)
    live_session_model.create_session(
        session_id=session_id,
        user_id=user.id,
        transcription_id=transcription_id,
        provider=provider,
        model=model,
        transport=transport,
        started_at=started_at,
    )
    return token


def _require_live_session(
    payload: Dict[str, Any],
    *,
    allow_closing: bool = False,
    allow_terminal: bool = False,
) -> Dict[str, Any]:
    """Load and validate the durable state referenced by a signed token."""
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not LIVE_SESSION_ID_PATTERN.fullmatch(session_id):
        raise LiveTranscriptionValidationError(_("The live session token is invalid."))
    session = live_session_model.get_session(session_id)
    if not session:
        raise LiveTranscriptionValidationError(
            _("The live session is no longer available.")
        )
    # The signed token is the client-held reference, but the durable row is
    # authoritative. Refuse a validly signed token if its identity no longer
    # matches the row it names (for example after accidental row/token mix-up).
    row_session_id = session.get("session_id")
    if row_session_id is not None and str(row_session_id) != session_id:
        raise LiveTranscriptionValidationError(
            _("The live session token is invalid.")
        )
    row_user_id = session.get("user_id")
    token_user_id = payload.get("user_id")
    if row_user_id is not None:
        try:
            if int(row_user_id) != int(token_user_id):
                raise LiveTranscriptionValidationError(
                    _("The live session token is invalid.")
                )
        except (TypeError, ValueError) as exc:
            raise LiveTranscriptionValidationError(
                _("The live session token is invalid.")
            ) from exc
    for field in ("transcription_id", "provider", "model", "transport"):
        row_value = session.get(field)
        token_value = payload.get(field)
        if row_value is not None and token_value is not None:
            if str(row_value) != str(token_value):
                raise LiveTranscriptionValidationError(
                    _("The live session token is invalid.")
                )
    row_started_at = session.get("started_at")
    if row_started_at is not None:
        try:
            if not math.isclose(
                float(row_started_at),
                float(payload.get("started_at")),
                rel_tol=0.0,
                abs_tol=1e-6,
            ):
                raise LiveTranscriptionValidationError(
                    _("The live session token is invalid.")
                )
        except (TypeError, ValueError) as exc:
            raise LiveTranscriptionValidationError(
                _("The live session token is invalid.")
            ) from exc
    status = str(session.get("status") or "")
    if status == "revoked":
        if allow_terminal:
            return session
        raise LiveTranscriptionValidationError(
            _("The live session is no longer available.")
        )
    if status == "finalized":
        if allow_terminal:
            return session
        raise LiveTranscriptionValidationError(
            _("The live session has already been finalized.")
        )
    if status == "finalizing":
        if allow_terminal:
            return session
        raise LiveTranscriptionValidationError(
            _("The live session is already being finalized.")
        )
    if status == "closing" and not allow_closing:
        raise LiveTranscriptionValidationError(
            _("The live session is no longer accepting audio.")
        )
    if status != "active" and status != "closing":
        raise LiveTranscriptionValidationError(_("The live session is invalid."))
    return session


def _release_openrouter_chunk_claim(session_id: str, sequence: int) -> None:
    """Best-effort release for every exception after a chunk claim."""
    try:
        live_session_model.release_chunk_sequence(session_id, sequence)
    except Exception:
        # Preserve the original provider/application exception while making
        # the failed release visible for operational follow-up.
        LOGGER.exception(
            "Could not release OpenRouter live chunk claim session=%s sequence=%s.",
            session_id,
            sequence,
        )


def _resolve_provider_api_key(user, provider: str, model: Optional[str] = None) -> str:
    api_key = user_service.get_decrypted_api_key(user.id, provider, model)
    if api_key:
        return api_key
    if access_service.is_team_mode():
        if check_permission(user, "allow_api_key_management"):
            raise MissingApiKeyError(_("%(provider)s API key is not configured.", provider=provider.title()))
        api_key = user_service.get_admin_decrypted_api_key(provider, model)
        if api_key:
            return api_key
    # Personal mode (or no admin key): fall back to the .env key.
    api_key = current_app.config.get(f"{provider.upper()}_API_KEY")
    if not api_key:
        raise MissingApiKeyError(_("%(provider)s API key is not configured.", provider=provider.title()))
    return api_key


def _resolve_openai_api_key(user, model: Optional[str] = None) -> str:
    return _resolve_provider_api_key(user, "openai", model)


def _validate_settings(user, language_code: str, context_prompt: str) -> tuple[str, str]:
    language = (language_code or "auto").strip().lower()
    prompt = (context_prompt or "").strip()
    supported_languages = transcription_catalog_model.get_language_map()
    if language != "auto" and language not in supported_languages:
        raise LiveTranscriptionValidationError(_("Select a supported transcription language."))
    if prompt and not check_permission(user, "allow_context_prompt"):
        raise LiveTranscriptionPermissionError(
            _("You do not have permission to use a context prompt.")
        )
    if len(prompt.split()) > MAX_CONTEXT_WORDS:
        raise LiveTranscriptionValidationError(
            _("Context prompt cannot exceed %(count)s words.", count=MAX_CONTEXT_WORDS)
        )
    return language, prompt


def build_session_config(model: str, language: str, prompt: str) -> Dict[str, Any]:
    transcription: Dict[str, Any] = {
        "model": model,
        "delay": "low",
    }
    if prompt:
        transcription["prompt"] = prompt
    if language != "auto":
        transcription["languages"] = [language]
    return {
        "type": "transcription",
        "audio": {
            "input": {
                "transcription": transcription,
                "turn_detection": None,
            }
        },
    }


def build_live_connect_constraints(model: str, language: str, prompt: str) -> Dict[str, Any]:
    """Build snake_case live_connect_constraints for Gemini ephemeral tokens."""
    transcription: Dict[str, Any] = {
        "language_codes": [] if language == "auto" else [language],
    }
    vocabulary = split_vocabulary_terms(prompt)
    if vocabulary:
        transcription["custom_vocabulary"] = vocabulary
    # Snake_case here matches the Python SDK auth_tokens.create config; the
    # browser-side setup frame uses camelCase siblings under setup instead.
    return {
        "model": model,
        "config": {
            "response_modalities": ["TEXT"],
            "input_audio_transcription": transcription,
            "session_resumption": {},
        },
    }


def _safety_identifier(user_id: int) -> str:
    secret = current_app.config["SECRET_KEY"].encode("utf-8")
    digest = hmac.new(secret, f"live:{user_id}".encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:64]


def _call_id_from_location(location: str) -> Optional[str]:
    match = re.search(r"/realtime/calls/([^/?#]+)", location or "")
    return match.group(1) if match else None


def _reserve_live_minutes_or_raise(user) -> None:
    """Reserve LIVE_MINUTES_RESERVATION against the user's role quota or fail."""
    role = getattr(user, "role", None)
    if role is None:
        raise LiveTranscriptionPermissionError(
            _("No role is assigned to your account.")
        )
    try:
        allowed, reason = role_model.reserve_usage_if_allowed(
            user.id,
            role,
            live_minutes_to_add=LIVE_MINUTES_RESERVATION,
        )
    except Exception:
        LOGGER.exception("Could not verify live transcription usage limits.")
        raise LiveTranscriptionUpstreamError(
            _("Could not verify your usage limits. Please try again.")
        )
    if not allowed:
        raise LiveTranscriptionPermissionError(reason)


def create_session(
    user, sdp: str, language_code: str, context_prompt: str,
    requested_model: Optional[str] = None,
) -> Dict[str, str]:
    language, prompt = _validate_settings(user, language_code, context_prompt)
    model = _resolve_live_model(user, requested_model)
    provider = _resolve_provider(user, model)
    _ensure_live_provider_permission(user, provider, model)
    if provider == "openrouter":
        # OpenRouter documents HTTP audio input plus SSE model output, not a
        # WebRTC/WebSocket realtime session. The browser uses this signed
        # token while posting short, valid WAV payloads to the chunk endpoint.
        _reserve_live_minutes_or_raise(user)
        _resolve_provider_api_key(user, provider, model)
        transcription_id = str(uuid.uuid4())
        started_at = time.time()
        token = _issue_session_token(
            user,
            transcription_id,
            started_at,
            language,
            prompt,
            model,
            provider,
            "openrouter-sse",
            context_prompt=prompt,
        )
        return {
            "answer_sdp": "",
            "session_token": token,
            "transport": "openrouter-sse",
        }
    if provider == "gemini":
        # WebRTC offer is not required for the Gemini WebSocket transport.
        _reserve_live_minutes_or_raise(user)  # single reservation per logical session
        api_key = _resolve_provider_api_key(user, provider, model)
        constraints = build_live_connect_constraints(model, language, prompt)
        now = datetime.now(timezone.utc)
        gemini_client = None
        try:
            gemini_client = _gemini_client(api_key)
            token_obj = gemini_client.auth_tokens.create(
                config={
                    "uses": 1,
                    "expire_time": now + timedelta(minutes=30),
                    "new_session_expire_time": now + timedelta(minutes=1),
                    "live_connect_constraints": constraints,
                }
            )
        except Exception as exc:
            LOGGER.error("Gemini ephemeral token request failed: %s", exc)
            raise LiveTranscriptionUpstreamError(
                _("Could not connect to the live transcription service.")
            ) from exc
        finally:
            if gemini_client is not None:
                gemini_client.close()
        transcription_id = str(uuid.uuid4())
        started_at = time.time()
        token = _issue_session_token(
            user,
            transcription_id,
            started_at,
            language,
            prompt,
            model,
            provider,
            "gemini-wss",
            context_prompt=prompt,
        )
        return {
            "answer_sdp": "",
            "session_token": token,
            "transport": "gemini-wss",
            "ws_url": GEMINI_WS_URL,
            "ephemeral_token": token_obj.name,
        }
    if not isinstance(sdp, str) or not sdp.strip():
        raise LiveTranscriptionValidationError(_("A WebRTC session offer is required."))
    if provider != "openai":
        raise LiveTranscriptionValidationError(
            _("The selected Live transcription provider is not supported by this runtime yet.")
        )
    _reserve_live_minutes_or_raise(user)
    api_key = _resolve_provider_api_key(user, provider, model)
    session_config = build_session_config(model, language, prompt)

    max_retries = max(
        0, int(current_app.config.get("LIVE_TRANSCRIPTION_SESSION_MAX_RETRIES", 1))
    )
    retry_delay = max(
        0.0,
        float(current_app.config.get("LIVE_TRANSCRIPTION_SESSION_RETRY_DELAY", 0.25)),
    )
    response = None
    for attempt in range(max_retries + 1):
        try:
            response = httpx.post(
                "https://api.openai.com/v1/realtime/calls",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "OpenAI-Safety-Identifier": _safety_identifier(user.id),
                },
                files={
                    "sdp": (None, sdp, "application/sdp"),
                    "session": (None, json.dumps(session_config), "application/json"),
                },
                timeout=current_app.config.get("OPENAI_HTTP_TIMEOUT", 120),
            )
        except httpx.HTTPError as exc:
            LOGGER.error("OpenAI realtime session request failed: %s", exc)
            raise LiveTranscriptionUpstreamError(
                _("Could not connect to the live transcription service.")
            ) from exc

        if (
            response.status_code not in RETRYABLE_SESSION_STATUS_CODES
            or attempt >= max_retries
        ):
            break
        LOGGER.warning(
            "OpenAI realtime session returned transient HTTP %s; retrying (%s/%s).",
            response.status_code,
            attempt + 1,
            max_retries,
        )
        if retry_delay:
            time.sleep(retry_delay)

    assert response is not None
    if response.status_code >= 400:
        LOGGER.error(
            "OpenAI realtime session returned HTTP %s: %s",
            response.status_code,
            response.text[:1000],
        )
        raise LiveTranscriptionUpstreamError(
            _("The live transcription service rejected the session.")
        )

    call_id = _call_id_from_location(response.headers.get("Location", ""))
    if not call_id:
        LOGGER.error("OpenAI realtime session response did not include a call ID.")
        raise LiveTranscriptionUpstreamError(
            _("The live transcription service returned an incomplete session.")
        )

    transcription_id = str(uuid.uuid4())
    started_at = time.time()
    token = _issue_session_token(
        user,
        transcription_id,
        started_at,
        language,
        prompt,
        model,
        provider,
        "openai-webrtc",
        call_id=call_id,
        context_prompt=prompt,
    )
    return {"answer_sdp": response.text, "session_token": token}


def _decode_session_token(
    token: str, *, allow_expired_for_completion: bool = False
) -> Dict[str, Any]:
    if not token:
        raise LiveTranscriptionValidationError(_("The live session token is missing."))
    try:
        payload = _serializer().loads(token)
    except BadSignature as exc:
        raise LiveTranscriptionValidationError(_("The live session token is invalid.")) from exc
    required_fields = {
        "user_id",
        "transcription_id",
        "session_id",
        "started_at",
        "language",
        "context_prompt_used",
        "model",
        "provider",
        "transport",
    }
    if not isinstance(payload, dict) or not required_fields.issubset(payload):
        raise LiveTranscriptionValidationError(_("The live session token is invalid."))
    if not isinstance(payload.get("session_id"), str) or not LIVE_SESSION_ID_PATTERN.fullmatch(
        payload["session_id"]
    ):
        raise LiveTranscriptionValidationError(_("The live session token is invalid."))
    started_at = payload.get("started_at")
    if isinstance(started_at, bool):
        raise LiveTranscriptionValidationError(_("The live session token is invalid."))
    try:
        started_at = float(started_at)
    except (TypeError, ValueError, OverflowError) as exc:
        raise LiveTranscriptionValidationError(_("The live session token is invalid.")) from exc
    if not math.isfinite(started_at):
        raise LiveTranscriptionValidationError(_("The live session token is invalid."))
    now = time.time()
    if started_at > now + MAX_SESSION_CLOCK_SKEW_SECONDS:
        raise LiveTranscriptionValidationError(_("The live session token is invalid."))
    max_age = MAX_SESSION_DURATION_MINUTES * 60
    if allow_expired_for_completion:
        # Stopping or saving must still work after the recording limit. These
        # operations cannot submit more audio, and the durable row bounds replay.
        max_age += live_session_model.LIVE_SESSION_RETENTION_SECONDS
    if now - started_at >= max_age:
        raise LiveTranscriptionValidationError(
            _("The live session has reached its maximum duration.")
        )
    payload["started_at"] = started_at
    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        raise LiveTranscriptionValidationError(_("The live session token is invalid."))
    if not isinstance(payload.get("provider"), str) or not payload["provider"].strip():
        raise LiveTranscriptionValidationError(_("The live session token is invalid."))
    if not isinstance(payload.get("transport"), str) or not payload["transport"].strip():
        raise LiveTranscriptionValidationError(_("The live session token is invalid."))
    return payload


def _iter_sse_data(lines):
    """Yield complete SSE data fields and ignore OpenRouter keep-alives."""
    data_lines = []
    for raw_line in lines:
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else str(raw_line)
        line = line.rstrip("\r")
        if not line:
            if data_lines:
                yield "\n".join(data_lines)
                data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        yield "\n".join(data_lines)


def transcribe_openrouter_chunk(
    user,
    session_token: str,
    audio_data: str,
    audio_format: str,
    sequence: int,
) -> Dict[str, Any]:
    """Transcribe one browser-produced audio chunk through OpenRouter SSE."""
    payload = _decode_session_token(session_token)
    _require_live_session(payload)
    if int(payload["user_id"]) != int(user.id):
        raise LiveTranscriptionPermissionError(_("This live session belongs to another user."))
    if payload.get("provider") != "openrouter":
        raise LiveTranscriptionValidationError(_("This live session does not use OpenRouter."))
    model = str(payload.get("model") or "").strip()
    _ensure_live_provider_permission(user, "openrouter", model)
    if not isinstance(sequence, int) or sequence < 0:
        raise LiveTranscriptionValidationError(_("The live audio sequence is invalid."))
    if not isinstance(audio_data, str) or not audio_data:
        raise LiveTranscriptionValidationError(_("The live audio chunk is missing."))
    normalized_format = str(audio_format or "").strip().lower().split(";")[0]
    if normalized_format not in OPENROUTER_AUDIO_FORMATS:
        raise LiveTranscriptionValidationError(_("The live audio format is not supported."))
    try:
        decoded_audio = base64.b64decode(audio_data, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise LiveTranscriptionValidationError(_("The live audio chunk is invalid.")) from exc
    if not decoded_audio or len(decoded_audio) > MAX_OPENROUTER_CHUNK_BYTES:
        raise LiveTranscriptionValidationError(_("The live audio chunk is too large."))

    api_key = _resolve_provider_api_key(user, "openrouter", model)
    instruction = (
        "Transcribe only the spoken words in this audio. Return only the transcript."
    )
    context_prompt = str(payload.get("context_prompt") or "").strip()
    if context_prompt:
        instruction += (
            f" Use this context for names and terminology: {context_prompt}"
        )
    request_body: Dict[str, Any] = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": instruction,
                },
                {
                    "type": "input_audio",
                    "input_audio": {"data": audio_data, "format": normalized_format},
                },
            ],
        }],
        "stream": True,
    }
    language = payload.get("language")
    if language and language != "auto":
        request_body["messages"][0]["content"][0]["text"] += f" The language is {language}."

    claim = live_session_model.claim_chunk_sequence(payload["session_id"], sequence)
    if claim.get("missing"):
        raise LiveTranscriptionValidationError(
            _("The live session is no longer available.")
        )
    if claim.get("status") in {"closing", "finalizing", "finalized", "revoked"}:
        raise LiveTranscriptionValidationError(
            _("The live session is no longer accepting audio.")
        )
    if claim.get("duplicate"):
        if claim.get("in_progress"):
            raise LiveTranscriptionValidationError(
                _("The live audio chunk is already being processed.")
            )
        return {
            "sequence": sequence,
            "transcript": claim.get("transcript", ""),
        }
    if not claim.get("claimed"):
        raise LiveTranscriptionValidationError(
            _("The live audio sequence is out of order.")
        )

    transcript_parts = []
    try:
        base_url = current_app.config.get(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ).rstrip("/")
        with httpx.stream(
            "POST",
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=request_body,
            timeout=current_app.config.get("OPENAI_HTTP_TIMEOUT", 120),
        ) as response:
            if response.status_code >= 400:
                LOGGER.error("OpenRouter live request returned HTTP %s.", response.status_code)
                raise LiveTranscriptionUpstreamError(
                    _("OpenRouter rejected the live audio chunk.")
                )
            for raw_event in _iter_sse_data(response.iter_lines()):
                if raw_event == "[DONE]":
                    break
                try:
                    event = json.loads(raw_event)
                except json.JSONDecodeError:
                    LOGGER.warning("Ignoring malformed OpenRouter live SSE event.")
                    continue
                if event.get("error"):
                    raise LiveTranscriptionUpstreamError(
                        _("OpenRouter reported an error while transcribing live audio.")
                    )
                choices = event.get("choices") or []
                delta = choices[0].get("delta") if choices else {}
                content = delta.get("content") if isinstance(delta, dict) else None
                if isinstance(content, str) and content:
                    transcript_parts.append(content)
    except LiveTranscriptionUpstreamError:
        _release_openrouter_chunk_claim(payload["session_id"], sequence)
        raise
    except httpx.HTTPError as exc:
        _release_openrouter_chunk_claim(payload["session_id"], sequence)
        LOGGER.error("OpenRouter live request failed: %s", exc)
        raise LiveTranscriptionUpstreamError(
            _("Could not connect to the OpenRouter live transcription service.")
        ) from exc
    except Exception:
        _release_openrouter_chunk_claim(payload["session_id"], sequence)
        raise

    transcript = "".join(transcript_parts).strip()
    try:
        live_session_model.record_chunk_result(
            payload["session_id"], sequence, transcript
        )
    except Exception:
        _release_openrouter_chunk_claim(payload["session_id"], sequence)
        raise
    return {"sequence": sequence, "transcript": transcript}


def hangup_session(user, session_token: str) -> Dict[str, bool]:
    payload = _decode_session_token(session_token, allow_expired_for_completion=True)
    session = _require_live_session(
        payload,
        allow_closing=True,
        allow_terminal=True,
    )
    if int(payload["user_id"]) != int(user.id):
        raise LiveTranscriptionPermissionError(
            _("This live session belongs to another user.")
        )
    provider = str(payload.get("provider") or "").strip().lower()
    model = str(payload.get("model") or "").strip()
    _ensure_live_provider_permission(user, provider, model)
    transport = session.get("transport") or payload.get("transport")
    status = session.get("status")
    if status == "revoked":
        return {"stopped": True}

    # A closing row without a completion marker means a prior provider stop
    # either failed or the process died before recording success. Keep retrying
    # that provider stop instead of treating the state transition as success.
    hangup_completed = bool(session.get("hangup_completed_at"))
    if status == "active":
        hangup = live_session_model.mark_hangup(payload["session_id"])
        if not hangup.get("found"):
            raise LiveTranscriptionValidationError(
                _("The live session is no longer available.")
            )
        session = live_session_model.get_session(payload["session_id"]) or session
        status = session.get("status")
        hangup_completed = bool(session.get("hangup_completed_at"))
    if hangup_completed:
        return {"stopped": True}

    if transport in ("openrouter-sse", "gemini-wss"):
        # Nothing to terminate server-side: OpenRouter SSE chunks and Gemini
        # WebSocket sessions simply end when the browser disconnects.
        live_session_model.mark_hangup_complete(payload["session_id"])
        return {"stopped": True}
    call_id = payload.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise LiveTranscriptionValidationError(_("The live session cannot be stopped."))

    try:
        response = httpx.post(
            f"https://api.openai.com/v1/realtime/calls/{call_id}/hangup",
            headers={"Authorization": f"Bearer {_resolve_openai_api_key(user, payload.get('model'))}"},
            timeout=current_app.config.get("OPENAI_HTTP_TIMEOUT", 120),
        )
    except httpx.HTTPError as exc:
        LOGGER.warning(
            "Could not explicitly stop OpenAI realtime call %s: %s",
            call_id,
            exc,
        )
        raise LiveTranscriptionUpstreamError(
            _("Could not stop the live transcription service.")
        ) from exc

    if (
        response.status_code >= 400
        and response.status_code not in ENDED_CALL_STATUS_CODES
    ):
        LOGGER.warning(
            "OpenAI realtime hangup returned HTTP %s for call %s.",
            response.status_code,
            call_id,
        )
        raise LiveTranscriptionUpstreamError(
            _("Could not stop the live transcription service.")
        )
    live_session_model.mark_hangup_complete(payload["session_id"])
    return {"stopped": True}


def refresh_session_token(user, session_token: str) -> Dict[str, str]:
    """Mint a fresh Gemini ephemeral token without re-reserving live minutes."""
    payload = _decode_session_token(session_token)
    _require_live_session(payload)
    if int(payload["user_id"]) != int(user.id):
        raise LiveTranscriptionPermissionError(
            _("This live session belongs to another user.")
        )
    if payload.get("provider") != "gemini" or payload.get("transport") != "gemini-wss":
        raise LiveTranscriptionValidationError(_("The live session cannot be refreshed."))
    _ensure_live_provider_permission(user, "gemini", str(payload.get("model") or "").strip())
    if time.time() - float(payload["started_at"]) >= MAX_SESSION_DURATION_MINUTES * 60:
        raise LiveTranscriptionValidationError(
            _("The live session has reached its maximum duration.")
        )
    # One reservation per logical session happened at create_session; a refresh
    # only mints a new ephemeral WebSocket credential.
    api_key = _resolve_provider_api_key(user, "gemini", payload["model"])
    constraints = build_live_connect_constraints(
        payload["model"], payload["language"], payload.get("context_prompt", "")
    )
    now = datetime.now(timezone.utc)
    gemini_client = None
    try:
        gemini_client = _gemini_client(api_key)
        token_obj = gemini_client.auth_tokens.create(
            config={
                "uses": 1,
                "expire_time": now + timedelta(minutes=30),
                "new_session_expire_time": now + timedelta(minutes=1),
                "live_connect_constraints": constraints,
            }
        )
    except Exception as exc:
        LOGGER.error("Gemini ephemeral token request failed: %s", exc)
        raise LiveTranscriptionUpstreamError(
            _("Could not connect to the live transcription service.")
        ) from exc
    finally:
        if gemini_client is not None:
            gemini_client.close()
    return {"ephemeral_token": token_obj.name, "ws_url": GEMINI_WS_URL}


def _resolve_saved_language(requested: Optional[str], detected: Optional[str]) -> str:
    """Pick the language to persist: API-detected first, then requested, else unknown."""
    if isinstance(detected, str):
        candidate = detected.strip().lower()
        if (
            candidate
            and len(candidate) <= 12
            and not any(char.isspace() or char == "/" for char in candidate)
        ):
            return candidate
    if requested and requested != "auto":
        return requested
    return "unknown"


def finalize_session(
    user,
    session_token: str,
    transcript: str,
    detected_language: Optional[str] = None,
) -> Dict[str, Any]:
    payload = _decode_session_token(session_token, allow_expired_for_completion=True)
    session = _require_live_session(
        payload,
        allow_closing=True,
        allow_terminal=True,
    )
    if int(payload["user_id"]) != int(user.id):
        raise LiveTranscriptionPermissionError(
            _("This live session belongs to another user.")
        )

    if session.get("status") == "revoked":
        raise LiveTranscriptionValidationError(
            _("The live session is no longer available.")
        )

    transcription_id = str(payload["transcription_id"])
    session_model = str(payload.get("model") or _resolve_live_model(user))
    _ensure_live_provider_permission(
        user,
        str(payload.get("provider") or _resolve_provider(user, session_model)),
        session_model,
    )
    existing = transcription_model.get_transcription_by_id(transcription_id, user.id)
    if existing:
        if existing.get("api_used") != session_model:
            raise LiveTranscriptionPermissionError(
                _("The live session identifier is already in use.")
            )
    if session.get("status") == "finalized":
        return {"transcription_id": transcription_id, "saved": True}
    if existing and existing.get("status") == "finished":
        finalize_state = live_session_model.begin_finalize(payload["session_id"])
        if finalize_state == "claimed":
            live_session_model.complete_finalize(payload["session_id"])
        elif finalize_state not in {"finalized", "in_progress"}:
            raise LiveTranscriptionValidationError(
                _("The live session is no longer available.")
            )
        return {"transcription_id": transcription_id, "saved": True}

    text = transcript.strip() if isinstance(transcript, str) else ""
    if not text:
        raise LiveTranscriptionValidationError(_("There is no transcript to save."))
    if len(text) > MAX_TRANSCRIPT_CHARS:
        raise LiveTranscriptionValidationError(
            _("The live transcript is too large to save.")
        )

    finalize_state = live_session_model.begin_finalize(payload["session_id"])
    if finalize_state == "finalized":
        return {"transcription_id": transcription_id, "saved": True}
    if finalize_state != "claimed":
        if finalize_state == "revoked":
            raise LiveTranscriptionValidationError(
                _("The live session is no longer available.")
            )
        raise LiveTranscriptionValidationError(
            _("The live session is already being finalized.")
        )

    try:
        started_at = float(payload["started_at"])
        duration_minutes = min(
            MAX_SESSION_DURATION_MINUTES,
            max(0.0, (time.time() - started_at) / 60.0),
        )
        language = _resolve_saved_language(payload["language"], detected_language)
        model = session_model
        filename = datetime.now(timezone.utc).strftime(
            "Live transcription %Y-%m-%d %H-%M UTC"
        )
        price = pricing_service.get_price("transcription", model)
        cost = (price or 0.0) * duration_minutes

        if not existing:
            transcription_model.create_transcription_job(
                transcription_id,
                user.id,
                filename,
                model,
                0.0,
                duration_minutes,
                bool(payload["context_prompt_used"]),
            )
        transcription_model.update_transcription_cost(transcription_id, cost)
        transcription_model.finalize_job_success(transcription_id, text, language)
        role_model.increment_usage(
            user.id,
            cost,
            duration_minutes,
            # The LIVE_MINUTES_RESERVATION taken at session start already covered
            # the first minutes against the live-minutes quota; bill only the
            # overage so a session is not double-counted.
            live_minutes_processed=max(0.0, duration_minutes - LIVE_MINUTES_RESERVATION),
        )

        if user.enable_auto_title_generation and check_permission(
            user, "allow_auto_title_generation"
        ):
            enqueue_title_generation(current_app.config, transcription_id, user.id)
        else:
            transcription_model.update_title_generation_status(transcription_id, "disabled")
    except Exception:
        live_session_model.release_finalize(payload["session_id"])
        raise

    if not live_session_model.complete_finalize(payload["session_id"]):
        LOGGER.warning(
            "Live session %s was finalized in storage by another request.",
            payload["session_id"],
        )
    return {"transcription_id": transcription_id, "saved": True}
