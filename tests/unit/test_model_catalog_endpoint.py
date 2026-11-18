import os
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("MYSQL_USER", "test")
os.environ.setdefault("MYSQL_PASSWORD", "test")
os.environ.setdefault("MYSQL_DB", "test_db")

import pytest
from flask import Flask
from flask_babel import Babel

from app.api import user_settings
from app.models import llm_catalog, transcription_catalog
from app.services import user_service


@pytest.fixture
def catalog_app():
    """A bare Flask app exposing only the user_settings blueprint."""
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    # Skips flask-login's authenticated check; the handler's own current_user
    # is patched per-test below.
    app.config["LOGIN_DISABLED"] = True
    # _() needs the Babel extension registered on the app.
    Babel(app)
    app.register_blueprint(user_settings.user_settings_bp)
    return app


FAKE_USER = SimpleNamespace(id=7, username="cataloguser", is_authenticated=True)
_REAL_EFFECTIVE_KEY_STATUS = user_service.get_effective_key_status


def register_builder_patches(stack: ExitStack, key_status):
    """Register patches for every collaborator the model-catalog endpoint
    composes, mirroring inject_global_vars' pipeline."""
    fixtures = SimpleNamespace(
        transcription_rows=[{"code": "gpt-4o-transcribe", "display_name": "GPT"}],
        transcription_options=[{"code": "gpt-4o-transcribe", "model_key": "openai:gpt-4o-transcribe"}],
        live_models=[{"code": "gpt-live-transcribe", "model_key": "openai:gpt-live-transcribe"}],
        llm_rows=[{"code": "gemini-flash", "display_name": "Gemini Flash", "required_api_key": "gemini"}],
        llm_filtered=[{"code": "gemini-flash", "display_name": "Gemini Flash", "required_api_key": "gemini", "filtered": True}],
    )
    stack.enter_context(patch.multiple(
        transcription_catalog,
        get_active_models=lambda: fixtures.transcription_rows,
        build_model_options=lambda models, status: fixtures.transcription_options,
        get_live_models=lambda status: fixtures.live_models,
    ))
    stack.enter_context(patch.multiple(
        llm_catalog,
        get_active_models=lambda: fixtures.llm_rows,
        filter_models_by_api_key_status=lambda models, status, *, allow_provider_wide: fixtures.llm_filtered,
    ))
    stack.enter_context(patch.multiple(
        user_service,
        get_effective_key_status=lambda user: key_status,
    ))
    return fixtures


def test_multi_user_response_mirrors_the_page_context_builders(catalog_app):
    key_status = {
        "provider_keys": {
            "openai": [{"model_name": "gpt-4o-transcribe", "model_purposes": ["transcription"]}],
        },
        "openai": True,
    }
    catalog_app.config["DEPLOYMENT_MODE"] = "multi"

    with ExitStack() as stack:
        fixtures = register_builder_patches(stack, key_status)
        with patch.object(user_settings, "current_user", FAKE_USER):
            response = catalog_app.test_client().get("/api/user/model-catalog")

    assert response.status_code == 200
    assert response.get_json() == {
        "transcription": fixtures.transcription_options,
        "live": fixtures.live_models,
        "llm": fixtures.llm_filtered,
    }


def test_multi_user_passes_effective_key_status_to_every_builder(catalog_app):
    key_status = {"provider_keys": {"openai": []}, "openai": False}
    catalog_app.config["DEPLOYMENT_MODE"] = "multi"

    with ExitStack() as stack:
        register_builder_patches(stack, key_status)
        with patch.object(user_settings, "current_user", FAKE_USER):
            with patch.object(
                transcription_catalog, "build_model_options",
                wraps=transcription_catalog.build_model_options,
            ) as build_options_spy, patch.object(
                transcription_catalog, "get_live_models",
                wraps=transcription_catalog.get_live_models,
            ) as live_spy, patch.object(
                llm_catalog, "filter_models_by_api_key_status",
                side_effect=lambda models, status, *, allow_provider_wide: [],
            ) as filter_spy:
                response = catalog_app.test_client().get("/api/user/model-catalog")

    assert response.status_code == 200
    build_options_spy.assert_called_once()
    assert build_options_spy.call_args.args[1] is key_status
    live_spy.assert_called_once_with(key_status)

    assert filter_spy.call_args.kwargs["allow_provider_wide"] is False
    merged_status = filter_spy.call_args.args[1]
    # Provider booleans merge environment availability into the key status,
    # exactly like inject_global_vars does before filtering LLM entries.
    assert merged_status["provider_keys"] == key_status["provider_keys"]
    for service in ("openai", "assemblyai", "gemini", "openrouter"):
        assert merged_status[service] is False


def test_personal_mode_uses_owner_keys_and_allows_provider_wide(catalog_app):
    catalog_app.config["DEPLOYMENT_MODE"] = "single"
    catalog_app.config["OPENAI_API_KEY"] = "env-openai-key"
    catalog_app.config["ASSEMBLYAI_API_KEY"] = None
    catalog_app.config["GEMINI_API_KEY"] = None
    catalog_app.config["OPENROUTER_API_KEY"] = None

    with ExitStack() as stack:
        register_builder_patches(stack, {})
        with patch.object(user_settings, "current_user", FAKE_USER):
            with patch.object(
                user_service, "get_effective_key_status", side_effect=_REAL_EFFECTIVE_KEY_STATUS
            ), patch.object(
                user_service, "get_user_api_key_status", return_value={"provider_keys": {}}
            ) as own_keys_spy, patch.object(
                llm_catalog, "filter_models_by_api_key_status",
                side_effect=lambda models, status, *, allow_provider_wide: [],
            ) as filter_spy, patch.object(
                transcription_catalog, "build_model_options",
                side_effect=lambda models, status: [],
            ) as build_options_spy:
                response = catalog_app.test_client().get("/api/user/model-catalog")

    assert response.status_code == 200
    # Personal mode: the owner's own saved keys, plus the .env provider keys.
    own_keys_spy.assert_called_once_with(FAKE_USER.id)

    build_status = build_options_spy.call_args.args[1]
    assert build_status == {
        "provider_keys": {},
        "openai": True, "assemblyai": False, "gemini": False, "openrouter": False,
    }

    assert filter_spy.call_args.kwargs["allow_provider_wide"] is True


def test_builder_failure_returns_a_generic_error(catalog_app):
    catalog_app.config["DEPLOYMENT_MODE"] = "single"

    with patch.multiple(
        transcription_catalog,
        get_active_models=lambda: (_ for _ in ()).throw(RuntimeError("db down")),
    ), patch.object(user_settings, "current_user", FAKE_USER):
        response = catalog_app.test_client().get("/api/user/model-catalog")

    assert response.status_code == 500
    assert "error" in response.get_json()


def test_endpoint_contract_matches_the_inject_global_vars_pipeline():
    """The endpoint must reuse the same builders as the page context, so a
    fresh page render can never disagree with a refreshed modal dropdown."""
    init_source = open("app/__init__.py", encoding="utf-8").read()
    endpoint_source = open("app/api/user_settings.py", encoding="utf-8").read()

    shared_calls = [
        "transcription_catalog_model.get_active_models()",
        "transcription_catalog_model.build_model_options(",
        "transcription_catalog_model.get_live_models(initial_key_status)",
        "llm_catalog_model.get_active_models()",
        "llm_catalog_model.filter_models_by_api_key_status(",
        "user_service.get_effective_key_status(",
    ]
    for call in shared_calls:
        assert call in init_source
        assert call in endpoint_source
