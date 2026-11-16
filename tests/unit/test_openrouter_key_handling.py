from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from flask import Flask
import pytest

from app.forms import ApiKeyForm
from app.models import user_api_key
from app.services import llm_service, user_service


OPENROUTER_KEY = "sk-or-v1-abcdefghijklmnopqrstuvwxyzXYZ"


def _app():
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="test-secret",
        WTF_CSRF_ENABLED=False,
        DEPLOYMENT_MODE="multi",
        OPENROUTER_API_KEY="global-openrouter-key",
    )
    return app


def test_api_key_form_accepts_masked_openrouter_key():
    with _app().test_request_context("/"):
        form = ApiKeyForm(
            meta={"csrf": False},
            data={
                "service": "openrouter",
                "api_key": "***XYZ",
                "openrouter_model": "x-ai/grok-stt-1.0",
                "openrouter_model_purpose": "transcription",
            },
        )

        assert form.validate() is True


def test_save_masked_openrouter_key_reuses_saved_key_for_new_slug():
    app = _app()
    user = SimpleNamespace(id=7)
    security_service = Mock()
    security_service.encrypt_data.return_value = "encrypted"

    with app.app_context(), patch.object(
        user_service.user_model, "get_user_by_id", return_value=user
    ), patch.object(
        user_service, "get_decrypted_api_key", return_value=OPENROUTER_KEY
    ) as get_key, patch.object(
        user_service, "get_security_service", return_value=security_service
    ), patch.object(
        user_service.user_api_key_model, "upsert_api_key", return_value=True
    ) as upsert, patch.object(
        user_service.user_model, "update_user_preferences", return_value=True
    ):
        assert user_service.save_user_api_key(
            7,
            "openrouter",
            "***XYZ",
            openrouter_model="x-ai/grok-stt-1.0",
        ) is True

    get_key.assert_called_once_with(
        7,
        "openrouter",
        "x-ai/grok-stt-1.0",
        allow_model_fallback=True,
    )
    security_service.encrypt_data.assert_called_once_with(OPENROUTER_KEY)
    upsert.assert_called_once_with(
        7,
        "openrouter",
        "encrypted",
        "x-ai/grok-stt-1.0",
        model_purpose="transcription",
    )


@pytest.mark.parametrize(
    ("provider", "model", "existing_key"),
    [
        ("openai", "gpt-transcribe", "sk-openai-XYZ"),
        ("assemblyai", "universal", "assemblyai-XYZ"),
        ("gemini", "gemini-3.0-flash", "AIzaSy123XYZ"),
        ("openrouter", "x-ai/grok-stt-1.0", "sk-or-v1-XYZ"),
    ],
)
def test_save_masked_key_reuses_existing_provider_key_for_every_provider(
    provider, model, existing_key
):
    app = _app()
    user = SimpleNamespace(id=7)
    security_service = Mock()
    security_service.encrypt_data.return_value = "encrypted"

    with app.app_context(), patch.object(
        user_service.user_model, "get_user_by_id", return_value=user
    ), patch.object(
        user_service, "get_decrypted_api_key", return_value=existing_key
    ) as get_key, patch.object(
        user_service, "get_security_service", return_value=security_service
    ), patch.object(
        user_service.user_api_key_model, "upsert_api_key", return_value=True
    ) as upsert, patch.object(
        user_service.user_model, "update_user_preferences", return_value=True
    ), patch(
        "app.models.transcription_catalog.register_model_from_provider"
    ):
        assert user_service.save_user_api_key(
            7,
            provider,
            "***XYZ",
            model_name=model,
        ) is True

    get_key.assert_called_once_with(
        7,
        provider,
        model,
        allow_model_fallback=True,
    )
    security_service.encrypt_data.assert_called_once_with(existing_key)
    upsert.assert_called_once_with(
        7,
        provider,
        "encrypted",
        model,
        model_purpose="transcription",
    )


@pytest.mark.parametrize(
    ("provider", "existing_model", "requested_model"),
    [
        ("openai", "gpt-4o-transcribe", "gpt-transcribe"),
        ("assemblyai", "universal", "future-assembly-model"),
        ("gemini", "gemini-2.5-flash", "gemini-3.0-flash"),
        ("openrouter", "openai/gpt-transcribe", "x-ai/grok-stt-1.0"),
    ],
)
def test_masked_save_lookup_can_reuse_any_existing_model_key_for_provider(
    provider, existing_model, requested_model
):
    cursor = Mock()
    expected_record = {
        "id": 7,
        "provider_code": provider,
        "model_slug": existing_model,
        "encrypted_key": "encrypted",
    }
    cursor.fetchone.return_value = expected_record

    with patch.object(user_api_key, "get_cursor", return_value=cursor):
        record = user_api_key.get_api_key_record(
            7,
            provider,
            requested_model,
            allow_model_fallback=True,
        )

    assert record == expected_record
    sql, params = cursor.execute.call_args.args
    assert params == (7, provider, requested_model)
    assert "ORDER BY CASE WHEN model_slug = %s THEN 0 ELSE 1 END" in sql
    assert "model_slug = %s OR model_slug = ''" not in sql


def test_save_full_model_key_overrides_preloaded_provider_key():
    app = _app()
    user = SimpleNamespace(id=7)
    security_service = Mock()
    security_service.encrypt_data.return_value = "encrypted-specific"

    with app.app_context(), patch.object(
        user_service.user_model, "get_user_by_id", return_value=user
    ), patch.object(
        user_service, "get_decrypted_api_key", return_value="provider-key"
    ) as get_key, patch.object(
        user_service, "get_security_service", return_value=security_service
    ), patch.object(
        user_service.user_api_key_model, "upsert_api_key", return_value=True
    ) as upsert:
        assert user_service.save_user_api_key(
            7,
            "openai",
            "model-specific-key",
            model_name="whisper",
        ) is True

    get_key.assert_not_called()
    security_service.encrypt_data.assert_called_once_with("model-specific-key")
    upsert.assert_called_once_with(
        7,
        "openai",
        "encrypted-specific",
        "whisper",
        model_purpose="transcription",
    )


def test_save_legacy_assemblyai_key_uses_the_universal_model_code():
    app = _app()
    user = SimpleNamespace(id=7)
    security_service = Mock()
    security_service.encrypt_data.return_value = "encrypted-assemblyai"

    with app.app_context(), patch.object(
        user_service.user_model, "get_user_by_id", return_value=user
    ), patch.object(
        user_service, "get_security_service", return_value=security_service
    ), patch.object(
        user_service.user_api_key_model, "upsert_api_key", return_value=True
    ) as upsert, patch(
        "app.models.transcription_catalog.register_model_from_provider"
    ) as register:
        assert user_service.save_user_api_key(
            7,
            "assemblyai",
            "assemblyai-key",
        ) is True

    upsert.assert_called_once_with(
        7,
        "assemblyai",
        "encrypted-assemblyai",
        "universal",
        model_purpose="transcription",
    )
    register.assert_called_once_with(
        provider="assemblyai",
        code="universal",
        display_name="universal",
        model_purpose="transcription",
    )


def test_status_exposes_openrouter_slugs_and_only_key_suffixes():
    app = _app()
    user = SimpleNamespace(
        role=SimpleNamespace(allow_public_api_access=False),
    )
    records = [
        {
            "provider_code": "openrouter",
            "model_slug": "x-ai/grok-stt-1.0",
            "model_purposes": "transcription,live",
            "encrypted_key": "encrypted-new",
        },
        {
            "provider_code": "openrouter",
            "model_slug": "openai/gpt-4.1-mini",
            "encrypted_key": "encrypted-old",
        },
    ]

    security_service = Mock()
    security_service.decrypt_data.side_effect = {
        "encrypted-new": "sk-or-v1-newXYZ",
        "encrypted-old": "sk-or-v1-oldABC",
    }.get

    with app.app_context(), patch.object(
        user_service.user_model, "get_user_by_id", return_value=user
    ), patch.object(
        user_service.user_api_key_model,
        "get_api_key_records_by_user",
        return_value=records,
    ), patch.object(
        user_service, "get_security_service", return_value=security_service
    ):
        status = user_service.get_user_api_key_status(7)

    assert status["openrouter"] is True
    assert status["openrouter_keys"] == [
        {"model_slug": "x-ai/grok-stt-1.0", "last_three": "XYZ"},
        {"model_slug": "openai/gpt-4.1-mini", "last_three": "ABC"},
    ]
    assert status["provider_keys"]["openrouter"][0]["model_purposes"] == [
        "transcription",
        "live",
    ]


def test_admin_model_key_lookup_requires_an_exact_model_row():
    app = _app()
    security_service = Mock()
    security_service.decrypt_data.side_effect = {
        "encrypted-specific": "admin-specific-key",
        "encrypted-wide": "admin-provider-key",
    }.get
    records = [
        {
            "id": 11,
            "user_id": 3,
            "model_slug": "whisper",
            "encrypted_key": "encrypted-specific",
        },
        {
            "id": 12,
            "user_id": 3,
            "model_slug": "",
            "encrypted_key": "encrypted-wide",
        },
    ]

    with app.app_context(), patch.object(
        user_service.user_api_key_model,
        "get_admin_api_key_records",
        return_value=records,
    ) as get_records, patch.object(
        user_service, "get_security_service", return_value=security_service
    ), patch.object(user_service.user_api_key_model, "mark_api_key_used") as mark_used:
        assert user_service.get_admin_decrypted_api_key("openai", "whisper") == "admin-specific-key"
        assert user_service.get_admin_decrypted_api_key("openai", "gpt-4o-transcribe") is None

    assert get_records.call_args_list == [
        call("openai", model_slug="whisper"),
        call("openai", model_slug="gpt-4o-transcribe"),
    ]
    mark_used.assert_called_once_with(3, 11)


def test_admin_named_model_query_excludes_provider_wide_rows():
    cursor = Mock()
    cursor.fetchall.return_value = []

    with patch.object(user_api_key, "get_cursor", return_value=cursor):
        assert user_api_key.get_admin_api_key_records(
            "openai",
            model_slug="whisper",
        ) == []

    sql, params = cursor.execute.call_args.args
    assert params == ("openai", "whisper")
    assert "AND k.model_slug = %s" in sql
    assert "OR k.model_slug = ''" not in sql


def test_model_upsert_scopes_openrouter_key_by_model_slug():
    cursor = Mock()
    connection = Mock()
    cursor.rowcount = 1

    with patch.object(user_api_key, "get_cursor", return_value=cursor), patch.object(
        user_api_key, "get_db", return_value=connection
    ):
        assert user_api_key.upsert_api_key(
            7, "openrouter", "encrypted", "x-ai/grok-stt-1.0"
        ) is True

    sql, params = cursor.execute.call_args.args
    assert "model_slug" in sql
    assert params == (7, "openrouter", "x-ai/grok-stt-1.0", "encrypted")


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("openai", "gpt-transcribe"),
        ("assemblyai", "universal"),
        ("gemini", "gemini-3.0-flash"),
        ("openrouter", "x-ai/grok-stt-1.0"),
    ],
)
def test_model_upsert_scopes_each_provider_key_by_model_slug(provider, model):
    cursor = Mock()
    connection = Mock()
    cursor.rowcount = 1

    with patch.object(user_api_key, "get_cursor", return_value=cursor), patch.object(
        user_api_key, "get_db", return_value=connection
    ):
        assert user_api_key.upsert_api_key(7, provider, "encrypted", model) is True

    sql, params = cursor.execute.call_args.args
    assert "model_slug" in sql
    assert params == (7, provider, model, "encrypted")


def test_llm_service_passes_requested_openrouter_model_to_key_lookup():
    app = _app()
    user = SimpleNamespace(
        id=7,
        role=SimpleNamespace(),
        has_permission=lambda permission: True,
    )
    llm_client = Mock()
    llm_client.generate_text.return_value = "result"

    with app.app_context(), patch.object(
        llm_service.user_model, "get_user_by_id", return_value=user
    ), patch.object(
        llm_service.user_service,
        "get_decrypted_api_key",
        return_value=OPENROUTER_KEY,
    ) as get_key, patch.object(
        llm_service, "get_llm_client", return_value=llm_client
    ):
        assert llm_service.generate_text_via_llm(
            "OPENROUTER",
            "prompt",
            user_id=7,
            model="x-ai/grok-stt-1.0",
        ) == "result"

    get_key.assert_called_once_with(7, "openrouter", "x-ai/grok-stt-1.0")


def test_openrouter_key_lookup_does_not_fall_back_to_another_model():
    cursor = Mock()
    expected_record = {
        "id": 7,
        "provider_code": "openrouter",
        "model_slug": "x-ai/grok-stt-1.0",
        "encrypted_key": "encrypted",
    }
    cursor.fetchone.return_value = expected_record

    with patch.object(user_api_key, "get_cursor", return_value=cursor):
        record = user_api_key.get_api_key_record(
            7, "openrouter", "google/gemini-3.7-flash"
        )

    sql, params = cursor.execute.call_args.args
    assert record == expected_record
    assert params == (7, "openrouter", "google/gemini-3.7-flash")
    assert "AND model_slug = %s" in sql
    assert "ORDER BY CASE WHEN model_slug = %s THEN 0 ELSE 1 END" not in sql
    assert "model_slug = %s OR model_slug = ''" not in sql


def test_unscoped_openrouter_key_lookup_requires_a_provider_wide_row():
    cursor = Mock()
    cursor.fetchone.return_value = None

    with patch.object(user_api_key, "get_cursor", return_value=cursor):
        assert user_api_key.get_api_key_record(7, "openrouter") is None

    sql, params = cursor.execute.call_args.args
    assert params == (7, "openrouter", "")
    assert "AND model_slug = %s" in sql


def test_api_key_modal_contract_contains_requested_copy_and_selected_state():
    template = open(
        "app/templates/layout/modals/api_key_modal.html", encoding="utf-8"
    ).read()
    script = open("app/static/js/user_settings.js", encoding="utf-8").read()

    assert 'id="modelNameHint"' in template
    assert "Enter the OpenRouter model as vendor/model." in script
    # The whole purpose segment is selected (raised white + purple text), not an inner span.
    assert "has-[:checked]:bg-white" in template
    assert "has-[:checked]:shadow-raised" in template
    assert "has-[:checked]:text-primary" in template
    assert "peer-checked:bg-primary/10" not in template
    assert "modelPurposePreview" not in template
    assert "openrouter_keys" in script
    assert "***${" in script


def test_schema_creates_replacement_index_before_dropping_legacy_index():
    cursor = Mock()
    connection = Mock()
    cursor.fetchone.side_effect = [
        {"Type": "timestamp"},
        {"Type": "timestamp"},
        {"Field": "model_slug"},
        {"Field": "model_purposes"},
        {"Field": "last_used_at"},
        None,
        {"Key_name": "uq_user_provider"},
        None,
    ]
    cursor.fetchall.return_value = []

    with patch.object(user_api_key, "get_cursor", return_value=cursor), patch.object(
        user_api_key, "get_db", return_value=connection
    ):
        user_api_key.init_db_command()

    statements = [call.args[0] for call in cursor.execute.call_args_list]
    replacement_index_position = next(
        index
        for index, statement in enumerate(statements)
        if "ADD UNIQUE INDEX uq_user_provider_model" in statement
    )
    legacy_drop_position = next(
        index
        for index, statement in enumerate(statements)
        if "DROP INDEX uq_user_provider" in statement
    )

    assert replacement_index_position < legacy_drop_position
