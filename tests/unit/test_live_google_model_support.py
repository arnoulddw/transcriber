from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from flask import Flask
from flask_babel import Babel

from app.services import live_transcription_service as service


def test_gemini_live_model_resolves_to_gemini_and_serves_websocket_session(monkeypatch):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="test-secret",
        DEPLOYMENT_MODE="single",
        OPENAI_API_KEY="openai-key",
        GEMINI_API_KEY="gemini-key",
        LIVE_TRANSCRIPTION_MODEL="gemini-3.5-transcribe-live",
        LIVE_TRANSCRIPTION_MODELS=["gemini-3.5-transcribe-live"],
        LIVE_TRANSCRIPTION_PROVIDERS={"gemini-3.5-transcribe-live": "gemini"},
    )
    Babel(app)
    monkeypatch.setattr(service, "_validate_settings", lambda *_: ("auto", ""))
    monkeypatch.setattr(service, "_resolve_provider_api_key", lambda *_: "k")
    # Personal-mode owner: admin role, every live permission granted.
    monkeypatch.setattr(service, "check_permission", MagicMock(return_value=True))
    monkeypatch.setattr(service.user_service, "get_user_api_key_status", MagicMock(return_value={}))
    monkeypatch.setattr(
        service.role_model,
        "reserve_usage_if_allowed",
        MagicMock(return_value=(True, "")),
    )
    fake_client = MagicMock()
    fake_client.auth_tokens.create.return_value.name = "tokens/gemini-ephemeral"
    monkeypatch.setattr(service, "_gemini_client", lambda _api_key: fake_client)
    monkeypatch.setattr(service.live_session_model, "create_session", MagicMock())
    post = MagicMock()
    monkeypatch.setattr(service.httpx, "post", post)

    user = SimpleNamespace(id=7, role=SimpleNamespace(name="member"))
    with app.app_context():
        assert service._resolve_provider(user, "gemini-3.5-transcribe-live") == "gemini"
        result = service.create_session(user, None, "auto", "", "gemini-3.5-transcribe-live")

    assert result["transport"] == "gemini-wss"
    assert result["answer_sdp"] == ""
    assert result["session_token"]
    assert result["ws_url"].startswith("wss://generativelanguage.googleapis.com/")
    assert result["ephemeral_token"] == "tokens/gemini-ephemeral"
    post.assert_not_called()


def test_live_model_allowlist_accepts_a_google_named_model_before_upstream_call():
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="test-secret",
        LIVE_TRANSCRIPTION_MODEL="gemini-2.5-flash-native-audio",
        LIVE_TRANSCRIPTION_MODELS=["gemini-2.5-flash-native-audio"],
    )
    Babel(app)

    with app.app_context():
        assert service._resolve_live_model(
            SimpleNamespace(default_live_transcription_model=None, role=None),
            "gemini-2.5-flash-native-audio",
        ) == "gemini-2.5-flash-native-audio"


def test_live_provider_configuration_defaults_existing_models_to_openai():
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="test-secret",
        LIVE_TRANSCRIPTION_MODEL="gpt-live-transcribe",
        LIVE_TRANSCRIPTION_MODELS=["gpt-live-transcribe"],
    )
    Babel(app)

    with app.app_context():
        assert service._resolve_provider(SimpleNamespace(), "gpt-live-transcribe") == "openai"


def test_live_provider_api_key_lookup_is_model_scoped(monkeypatch):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="test-secret",
        DEPLOYMENT_MODE="multi",
        LIVE_TRANSCRIPTION_PROVIDERS={"gemini-2.5-flash-native-audio": "gemini"},
        GEMINI_API_KEY="global-gemini-key",
    )
    Babel(app)
    user = SimpleNamespace(id=7)
    monkeypatch.setattr(service, "check_permission", lambda *_: True)
    monkeypatch.setattr(service.user_service, "get_decrypted_api_key", lambda *_: None)

    with app.app_context():
        with pytest.raises(service.MissingApiKeyError):
            service._resolve_provider_api_key(user, "gemini", "gemini-2.5-flash-native-audio")


def test_live_provider_api_key_uses_admin_model_key_without_user_key_management(monkeypatch):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="test-secret",
        DEPLOYMENT_MODE="multi",
        OPENAI_API_KEY=None,
    )
    Babel(app)
    user = SimpleNamespace(id=7)
    monkeypatch.setattr(service, "check_permission", lambda *_: False)
    monkeypatch.setattr(service.user_service, "get_decrypted_api_key", lambda *_: None)
    get_admin_key = MagicMock(return_value="admin-model-key")
    monkeypatch.setattr(service.user_service, "get_admin_decrypted_api_key", get_admin_key)

    with app.app_context():
        assert service._resolve_provider_api_key(
            user,
            "openai",
            "gpt-live-transcribe",
        ) == "admin-model-key"

    get_admin_key.assert_called_once_with("openai", "gpt-live-transcribe")
