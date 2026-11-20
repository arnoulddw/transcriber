from contextlib import ExitStack
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from flask import Flask

from app.forms import AdminRoleForm, UserProfileForm
from app.config import Config
from app.models import llm_catalog
from app.models import transcription_catalog
from app.models.user.model import _map_row_to_user
from app.models.user.repository import update_user_preferences
from app.services import user_service


TRANSCRIPTION_MODELS = [
    {
        "code": "gpt-4o-transcribe",
        "display_name": "OpenAI GPT-4o Transcribe",
        "permission_key": None,
        "provider_code": "openai",
        "required_api_key": "openai",
    },
    {
        "code": "openai/gpt-transcribe",
        "display_name": "openai/gpt-transcribe",
        "permission_key": None,
        "provider_code": "openrouter",
        "required_api_key": "openrouter",
    },
    {
        "code": "qwen/qwen3-asr-1.7b",
        "display_name": "qwen/qwen3-asr-1.7b",
        "permission_key": None,
        "provider_code": "openrouter",
        "required_api_key": "openrouter",
    },
    {
        "code": "x-ai/grok-stt-1.0",
        "display_name": "x-ai/grok-stt-1.0",
        "permission_key": None,
        "provider_code": "openrouter",
        "required_api_key": "openrouter",
    },
]

# Key status used by the profile/role form fixtures: one OpenRouter
# transcription slug so the openrouter option resolves to a real model.
OPENROUTER_KEY_STATUS = {
    "provider_keys": {
        "openai": [
            {"model_name": "gpt-4o-transcribe", "model_purposes": ["transcription"]},
        ],
        "openrouter": [
            {"model_name": "openai/gpt-transcribe", "model_purposes": ["transcription"]},
        ],
    },
}


@pytest.fixture
def form_context():
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="test-secret",
        WTF_CSRF_ENABLED=False,
        SUPPORTED_LANGUAGES=["en"],
        SUPPORTED_LANGUAGE_NAMES={"auto": "Automatic Detection"},
    )
    fake_user = SimpleNamespace(
        is_authenticated=True,
        username="testuser",
        email="test@example.com",
    )
    with app.test_request_context("/"):
        with ExitStack() as stack:
            stack.enter_context(patch("app.forms.current_user", fake_user))
            stack.enter_context(patch("app.forms.get_user_by_username", return_value=None))
            stack.enter_context(patch("app.forms.get_user_by_email", return_value=None))
            stack.enter_context(patch("app.forms.get_role_by_name", return_value=None))
            stack.enter_context(
                patch(
                    "app.forms.transcription_catalog_model.get_active_languages",
                    return_value=[{"code": "auto", "display_name": "Automatic Detection"}],
                )
            )
            stack.enter_context(
                patch(
                    "app.forms.transcription_catalog_model.get_active_models",
                    return_value=TRANSCRIPTION_MODELS,
                )
            )
            stack.enter_context(
                patch("app.forms.llm_catalog_model.get_llm_model_options", return_value=[])
            )
            stack.enter_context(
                patch(
                    "app.forms.user_service.get_effective_key_status",
                    return_value=OPENROUTER_KEY_STATUS,
                )
            )
            stack.enter_context(
                patch(
                    "app.forms.user_service.get_admin_api_key_status",
                    return_value=OPENROUTER_KEY_STATUS,
                )
            )
            yield


def _form_data(form_type, transcription_model="openai/gpt-transcribe"):
    data = {
        "name": "test-role",
        "description": "A test role",
        "default_transcription_model": transcription_model,
    }
    # Only the user profile form still carries the (legacy, optional)
    # OpenRouter slug preference; the admin role form no longer has it.
    if form_type is UserProfileForm:
        data.update(
            {
                "username": "testuser",
                "email": "test@example.com",
                "default_content_language": "auto",
                "language": "en",
            }
        )
    return data


def test_user_row_maps_provider_neutral_preferences():
    user = _map_row_to_user(
        {
            "id": 7,
            "username": "testuser",
            "email": "test@example.com",
            "created_at": "2026-08-16T00:00:00",
            "default_title_generation_model": "gemma-4-26b-a4b-it",
            "default_workflow_model": "google/gemini-3.7-flash",
        }
    )

    assert user is not None
    assert user.default_title_generation_model == "gemma-4-26b-a4b-it"
    assert user.default_workflow_model == "google/gemini-3.7-flash"


def test_profile_form_exposes_permitted_llm_model_choices(form_context):
    llm_models = [
        {
            "code": "gemini-3.0-flash",
            "display_name": "Gemini 3.0 Flash",
            "permission_key": "use_api_google_gemini",
        },
        {
            "code": "gpt-4.1",
            "display_name": "OpenAI GPT-4.1",
            "permission_key": None,
        },
        {
            "code": "restricted-model",
            "display_name": "Restricted Model",
            "permission_key": "use_restricted_model",
        },
    ]
    authenticated_user = SimpleNamespace(
        is_authenticated=True,
        username="testuser",
        email="test@example.com",
        has_permission=lambda permission: permission == "use_api_google_gemini",
    )

    with patch("app.forms.current_user", authenticated_user), patch(
        "app.forms.llm_catalog_model.get_llm_model_options", return_value=llm_models
    ), patch(
        "app.forms.user_service.get_effective_key_status",
        return_value=OPENROUTER_KEY_STATUS,
    ):
        form = UserProfileForm(data=_form_data(UserProfileForm))

    expected_model_choices = [
        ("gemini-3.0-flash", "Gemini 3.0 Flash"),
        ("gpt-4.1", "OpenAI GPT-4.1"),
    ]
    workflow_choices = list(form.default_workflow_model.choices or [])
    auxiliary_choices = list(form.default_title_generation_model.choices or [])
    assert workflow_choices[0][0] == ""
    assert workflow_choices[1:] == expected_model_choices
    assert auxiliary_choices[0][0] == ""
    assert auxiliary_choices[1:] == expected_model_choices
    assert form.validate() is True


def test_llm_model_catalog_hides_models_without_an_available_provider_key():
    models = [
        {
            "code": "google/gemini-3.7-flash",
            "display_name": "Gemini 3.7 Flash (OpenRouter)",
            "required_api_key": "openrouter",
        },
        {
            "code": "gemini-3.0-flash",
            "display_name": "Gemini 3.0 Flash",
            "required_api_key": "gemini",
        },
        {
            "code": "local-model",
            "display_name": "Local Model",
            "required_api_key": None,
        },
    ]

    available_models = llm_catalog.filter_models_by_api_key_status(
        models,
        {
            "openrouter": True,
            "gemini": False,
            "provider_keys": {
                "openrouter": [
                    {
                        "model_name": "google/gemini-3.7-flash",
                        "provider_wide": True,
                        "model_purposes": ["llm"],
                    },
                ],
            },
        },
    )

    assert [model["code"] for model in available_models] == [
        "local-model",
    ]

    available_models = llm_catalog.filter_models_by_api_key_status(
        models,
        {
            "provider_keys": {
                "openrouter": [
                    {
                        "model_name": "google/gemini-3.7-flash",
                        "model_purposes": ["llm"],
                    },
                ],
            },
        },
    )
    assert [model["code"] for model in available_models] == [
        "google/gemini-3.7-flash",
        "local-model",
    ]


class _Cursor:
    rowcount = 1

    def __init__(self):
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))


class _Connection:
    def __init__(self):
        self.commit = Mock()
        self.rollback = Mock()


def test_repository_persists_and_clears_live_model_preference():
    cursor = _Cursor()
    connection = _Connection()

    with patch("app.models.user.repository.get_cursor", return_value=cursor), patch(
        "app.models.user.repository.get_db", return_value=connection
    ):
        assert update_user_preferences(
            7, None, None, None, None,
            default_live_transcription_model="openai:gpt-live-transcribe",
        ) is True
        assert update_user_preferences(
            7, None, None, None, None,
            default_live_transcription_model=None,
        ) is True

    assert "default_live_transcription_model = %s" in cursor.calls[0][0]
    assert cursor.calls[0][1] == ("openai:gpt-live-transcribe", 7)
    assert cursor.calls[1][1] == (None, 7)


def test_repository_old_call_shape_does_not_clear_new_preference():
    cursor = _Cursor()
    connection = _Connection()

    with patch("app.models.user.repository.get_cursor", return_value=cursor), patch(
        "app.models.user.repository.get_db", return_value=connection
    ):
        assert update_user_preferences(7, None, None, True, None) is True

    assert "default_live_transcription_model = %s" not in cursor.calls[0][0]


def test_repository_persists_new_llm_model_preferences():
    cursor = _Cursor()
    connection = _Connection()

    with patch("app.models.user.repository.get_cursor", return_value=cursor), patch(
        "app.models.user.repository.get_db", return_value=connection
    ):
        assert update_user_preferences(
            7,
            None,
            None,
            None,
            None,
            default_title_generation_model="gemma-4-26b-a4b-it",
            default_workflow_model="google/gemini-3.7-flash",
        ) is True

    assert "default_title_generation_model = %s" in cursor.calls[0][0]
    assert "default_workflow_model = %s" in cursor.calls[0][0]
    assert cursor.calls[0][1] == (
        "gemma-4-26b-a4b-it",
        "google/gemini-3.7-flash",
        7,
    )


def test_saved_openrouter_slug_is_visible_in_transcription_model_selectors():
    config = open("app/config.py", encoding="utf-8").read()
    compose = open("docker-compose.yml", encoding="utf-8").read()
    index_template = open("app/templates/index.html", encoding="utf-8").read()
    bootstrap_template = open(
        "app/templates/layout/scripts/base_bootstrap.html", encoding="utf-8"
    ).read()
    profile_script = open("app/static/js/profile.js", encoding="utf-8").read()
    main_init = open("app/static/js/main_init.js", encoding="utf-8").read()

    assert "assemblyai,openai,gemini,openrouter" in config
    # The compose default must mirror Config.TRANSCRIPTION_PROVIDERS exactly.
    assert (
        "TRANSCRIPTION_PROVIDERS: ${TRANSCRIPTION_PROVIDERS:-"
        + ",".join(Config.TRANSCRIPTION_PROVIDERS)
        + "}"
    ) in compose
    assert f"TRANSCRIPTION_PROVIDERS={','.join(Config.TRANSCRIPTION_PROVIDERS)}" in open(
        ".env.example", encoding="utf-8"
    ).read()
    # No OpenRouter slug preference survives anywhere: not the window global,
    # not a modal field, and the home-page hidden input no longer carries a
    # server-rendered default.
    assert "DEFAULT_OPENROUTER_MODEL" not in bootstrap_template
    assert "DEFAULT_OPENROUTER_MODEL" not in profile_script
    assert "default_openrouter_model" not in profile_script
    assert "initial_key_status.get('openrouter_keys', [])" not in index_template
    # The per-provider data-openrouter-model attribute is gone too: every
    # option's slug already lives in the uniform data-model-name attribute.
    assert "model.model_slug" not in index_template
    assert "data-openrouter-model" not in index_template
    # The home-page hidden slug input is gone too: every option is a concrete
    # model key, so the form never submits a provider-shaped bare 'openrouter'.
    assert "openrouterModelInput" not in index_template
    assert "TRANSCRIPTION_MODEL_CATALOG=available_transcription_models" in open("app/__init__.py", encoding="utf-8").read()
    assert "transcription_models=available_transcription_models" in open("app/__init__.py", encoding="utf-8").read()


def test_compose_passes_openrouter_key_to_web_service():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "OPENROUTER_API_KEY: ${OPENROUTER_API_KEY:-}" in compose


def test_live_openrouter_configuration_is_documented_and_detected():
    config_source = Path("app/config.py").read_text(encoding="utf-8")
    env_example = Path(".env.example").read_text(encoding="utf-8")
    live_service = Path("app/services/live_transcription_service.py").read_text(encoding="utf-8")
    main_init = Path("app/static/js/main_init.js").read_text(encoding="utf-8")
    profile_script = Path("app/static/js/profile.js").read_text(encoding="utf-8")

    assert "replace('/', '_')" in config_source
    assert "LIVE_TRANSCRIPTION_PROVIDER_OPENAI_GPT_TRANSCRIBE=openrouter" in env_example
    assert '"transport": "openrouter-sse"' in live_service
    assert "updateSelectedOpenRouterModel" not in main_init
    assert "openrouterModelField" not in main_init
    assert "const apiKeyStatus = window.API_KEY_STATUS || {};" in profile_script
    assert "opt.disabled = true;" in profile_script
    assert "missingKeyMarker" in profile_script


def test_shared_transcription_model_expansion_includes_all_openrouter_slugs():
    models = [
        {
            "code": "x-ai/grok-stt-1.0",
            "display_name": "x-ai/grok-stt-1.0",
            "permission_key": None,
            "provider_code": "openrouter",
            "required_api_key": "openrouter",
        },
        {
            "code": "openai/gpt-transcribe",
            "display_name": "openai/gpt-transcribe",
            "permission_key": None,
            "provider_code": "openrouter",
            "required_api_key": "openrouter",
        },
    ]

    expanded = transcription_catalog.expand_models_for_ui(
        models,
        {
            "openai": True,
            "openrouter_keys": [
                {"model_slug": "x-ai/grok-stt-1.0"},
                {"model_slug": "openai/gpt-transcribe"},
            ],
        },
    )

    assert [(model["code"], model["display_name"], model.get("model_slug")) for model in expanded] == [
        ("x-ai/grok-stt-1.0", "x-ai/grok-stt-1.0", "x-ai/grok-stt-1.0"),
        ("openai/gpt-transcribe", "openai/gpt-transcribe", "openai/gpt-transcribe"),
    ]


def test_scoped_transcription_key_only_expands_the_matching_catalog_model():
    models = [
        {"code": "whisper", "display_name": "Whisper", "permission_key": None, "required_api_key": "openai"},
        {"code": "gpt-4o-transcribe", "display_name": "GPT-4o", "permission_key": None, "required_api_key": "openai"},
        {"code": "gpt-transcribe", "display_name": "GPT", "permission_key": None, "required_api_key": "openai"},
    ]

    expanded = transcription_catalog.expand_models_for_ui(
        models,
        {
            "provider_keys": {
                "openai": [
                    {"model_name": "gpt-transcribe", "model_purposes": ["transcription"]},
                    {"model_name": "gpt-4.1", "model_purposes": ["llm"]},
                ],
            },
        },
    )

    assert [(model["code"], model.get("model_name")) for model in expanded] == [
        ("gpt-transcribe", "gpt-transcribe"),
    ]
    assert sum(model.get("model_name") == "gpt-transcribe" for model in expanded) == 1


def test_transcription_model_expansion_deduplicates_saved_model_names():
    models = [
        {
            "code": "openai/gpt-transcribe",
            "display_name": "openai/gpt-transcribe",
            "permission_key": None,
            "provider_code": "openrouter",
            "required_api_key": "openrouter",
        },
    ]

    expanded = transcription_catalog.expand_models_for_ui(
        models,
        {
            "provider_keys": {
                "openrouter": [
                    {"model_slug": "openai/gpt-transcribe", "model_purposes": ["transcription"]},
                    {"model_name": "openai/gpt-transcribe", "model_purposes": ["transcription"]},
                ],
            },
        },
    )

    assert [(model["code"], model.get("model_slug")) for model in expanded] == [
        ("openai/gpt-transcribe", "openai/gpt-transcribe"),
    ]


def test_live_model_catalog_deduplicates_configured_and_user_models(form_context):
    from flask import current_app

    current_app.config.update(
        LIVE_TRANSCRIPTION_MODEL="gpt-live-transcribe",
        LIVE_TRANSCRIPTION_MODELS=["gpt-live-transcribe", "gpt-live-transcribe"],
        LIVE_TRANSCRIPTION_PROVIDERS={"gpt-live-transcribe": "openai"},
    )

    # Catalog live rows come from the DB; mock it so the unit test stays
    # DB-free while exercising the dedupe against saved OpenRouter slugs.
    fake_cursor = Mock()
    fake_cursor.execute.return_value = None
    fake_cursor.fetchall.return_value = [
        {"code": "gpt-live-transcribe", "display_name": "GPT Live", "required_api_key": "openai"},
    ]
    with patch.object(transcription_catalog, "get_cursor", return_value=fake_cursor), \
         patch.object(transcription_catalog, "get_db"):
        live_models = transcription_catalog.get_live_models({
            "provider_keys": {
                "openrouter": [
                    {"model_slug": "vendor/live", "model_purposes": ["live"]},
                    {"model_slug": "vendor/live", "model_purposes": ["live"]},
                ],
            },
        })

    assert [model["code"] for model in live_models] == ["gpt-live-transcribe", "vendor/live"]


def test_service_save_never_touches_openrouter_preferences():
    """No profile submission path can write an OpenRouter slug preference
    any more: the columns are dropped and every caller is provider-neutral."""
    current_user = SimpleNamespace(
        username="testuser",
        email="test@example.com",
        first_name=None,
        last_name=None,
        default_content_language="auto",
        default_transcription_model="openai/gpt-transcribe",
        default_title_generation_model=None,
        default_workflow_model=None,
        enable_auto_title_generation=False,
        language="en",
    )
    update_preferences = Mock(return_value=True)

    with patch.object(user_service.user_model, "get_user_by_id", return_value=current_user), patch.object(
        user_service.user_model, "update_user_preferences", update_preferences
    ):
        user_service.update_profile(
            7,
            {
                "username": "testuser",
                "email": "test@example.com",
                "first_name": None,
                "last_name": None,
                "default_content_language": "auto",
                # A real change so the save reaches the preferences update.
                "default_transcription_model": "openai:gpt-transcribe",
                # Even if a stale client still sends these, they are ignored.
                "default_openrouter_model": " openai/gpt-transcribe ",
                "default_openrouter_llm_model": " google/gemini-3.7-flash ",
                "enable_auto_title_generation": False,
                "language": "en",
            },
        )

    called_kwargs = update_preferences.call_args.kwargs
    assert "default_openrouter_model" not in called_kwargs
    assert "default_openrouter_llm_model" not in called_kwargs


def test_service_passes_new_llm_model_preferences():
    current_user = SimpleNamespace(
        username="testuser",
        email="test@example.com",
        first_name=None,
        last_name=None,
        default_content_language="auto",
        default_transcription_model="gpt-4o-transcribe",
        default_title_generation_model=None,
        default_workflow_model=None,
        enable_auto_title_generation=False,
        language="en",
    )
    update_preferences = Mock(return_value=True)

    with patch.object(user_service.user_model, "get_user_by_id", return_value=current_user), patch.object(
        user_service.user_model, "update_user_preferences", update_preferences
    ):
        user_service.update_profile(
            7,
            {
                "username": "testuser",
                "email": "test@example.com",
                "first_name": None,
                "last_name": None,
                "default_content_language": "auto",
                "default_transcription_model": "gpt-4o-transcribe",
                "default_title_generation_model": " gemma-4-26b-a4b-it ",
                "default_workflow_model": " google/gemini-3.7-flash ",
                "enable_auto_title_generation": False,
                "language": "en",
            },
        )

    update_preferences.assert_called_once_with(
        7,
        "auto",
        "gpt-4o-transcribe",
        False,
        "en",
        default_title_generation_model="gemma-4-26b-a4b-it",
        default_workflow_model="google/gemini-3.7-flash",
    )


def test_admin_role_form_exposes_each_openrouter_slug_as_option(form_context):
    from unittest.mock import patch

    from app.forms import AdminRoleForm

    with patch(
        "app.forms.user_service.get_admin_api_key_status",
        return_value={
            "provider_keys": {
                "openrouter": [
                    # Reverse alphabetical on purpose: the canonical options
                    # list sorts slugs alphabetically.
                    {"model_name": "x-ai/grok-stt-1.0", "model_purposes": ["transcription"]},
                    {"model_name": "qwen/qwen3-asr-1.7b", "model_purposes": ["transcription"]},
                ],
            },
        },
    ):
        form = AdminRoleForm()

    or_options = [
        m for m in form.transcription_model_options
        if m.get("provider_code") == "openrouter"
    ]
    assert [m.get("code") for m in or_options] == ["qwen/qwen3-asr-1.7b", "x-ai/grok-stt-1.0"]
    assert [m.get("display_name") for m in or_options] == ["qwen/qwen3-asr-1.7b", "x-ai/grok-stt-1.0"]

    # WTForms choices use the qualified model identity so two providers can
    # safely expose the same provider-local code.
    values = [c[0] for c in form.default_transcription_model.choices or []]
    assert values == ["", "openrouter:qwen/qwen3-asr-1.7b", "openrouter:x-ai/grok-stt-1.0"]

    # A submitted qualified key (any of the options) validates against the choices.
    submit = AdminRoleForm(
        data={
            "name": "test-role",
            "default_transcription_model": "openrouter:qwen/qwen3-asr-1.7b",
        }
    )
    assert submit.validate() is True


def test_admin_role_form_does_not_keep_current_openrouter_slug_without_a_key(form_context):
    from unittest.mock import patch

    from app.forms import AdminRoleForm

    with patch(
        "app.forms.user_service.get_admin_api_key_status",
        return_value={"provider_keys": {"openrouter": []}},
    ):
        form = AdminRoleForm(
            obj=SimpleNamespace(
                name="legacy-role",
                default_transcription_model="openrouter",
            )
        )

    or_options = [m for m in form.transcription_model_options if m.get("code") == "openrouter"]
    assert or_options == []
