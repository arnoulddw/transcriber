import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _set_minimal_app_environment(monkeypatch):
    for key, value in {
        "SECRET_KEY": "ui-consistency-test-secret",
        "MYSQL_USER": "test",
        "MYSQL_PASSWORD": "test",
        "MYSQL_DB": "test_db",
        "GOOGLE_CLIENT_ID": "test-google-client-id",
        "DEPLOYMENT_MODE": "multi",
    }.items():
        monkeypatch.setenv(key, value)


def test_manage_api_key_purpose_controls_are_independent_of_service_selection():
    template = Path("app/templates/layout/modals/api_key_modal.html").read_text(encoding="utf-8")
    script = Path("app/static/js/user_settings.js").read_text(encoding="utf-8")

    assert "id=\"liveModelSettings\"" not in template
    assert "id=\"apiKeyLiveModel\"" not in template
    assert "purposeInputs.forEach(input => { input.disabled = !service; })" not in script
    assert "providerSelect.value = selectedOption.dataset.provider" not in script
    assert "input.addEventListener('change', () => updateModelSettings" in script


def test_admin_role_labels_match_user_settings_labels():
    admin_form_source = Path("app/forms.py").read_text(encoding="utf-8")
    settings_template = Path("app/templates/layout/modals/profile_modal.html").read_text(encoding="utf-8")

    assert "_('Default Auxiliary LLM Model')" in admin_form_source
    assert "_('Default Workflow LLM Model')" in admin_form_source
    assert "Default Auxiliary LLM Model" in settings_template
    assert "Default Workflow LLM Model" in settings_template
    assert "_('Default Title Generation Model')" not in admin_form_source
    assert "_('Default Workflow Model')" not in admin_form_source


def test_role_label_translations_match_the_updated_source_strings():
    for path in Path("app/translations").glob("*/LC_MESSAGES/messages.po"):
        source = path.read_text(encoding="utf-8")
        assert 'msgid "Default Auxiliary LLM Model"' in source
        assert 'msgid "Default Workflow LLM Model"' in source
        assert 'msgid "Default Title Generation Model"' not in source
        assert 'msgid "Default Workflow Model"' not in source


def test_history_renders_chunk_warning_after_title_icons():
    index_template = Path("app/templates/index.html").read_text(encoding="utf-8")
    history_render = Path("app/static/js/history/render.js").read_text(encoding="utf-8")
    history_polling = Path("app/static/js/history/polling.js").read_text(encoding="utf-8")
    main_poll = Path("app/static/js/main_poll.js").read_text(encoding="utf-8")
    progress_api = Path("app/api/transcriptions.py").read_text(encoding="utf-8")

    assert "has_transcription_warning" in index_template
    assert "title-warning-icon-{{ transcription.id }}" in index_template
    assert "text-red-600" in index_template
    assert ">error_outline</i>" in index_template
    assert "title=\"{{ _('Transcript may be incomplete') }}\"" in index_template
    assert "aria-label=\"{{ _('Transcript may be incomplete') }}\"" in index_template
    assert "transcriptionWarningIconHtml" in history_render
    assert "title=\"Transcript may be incomplete\"" in history_render
    assert "aria-label=\"Transcript may be incomplete\"" in history_render
    assert "title-warning-icon-${transcription.id}" in history_render
    assert "warningIconHtml" in history_polling
    assert "has_transcription_warning" in progress_api
    assert "hasTranscriptionWarning" in main_poll


def test_index_template_has_first_run_empty_state_warning_with_manage_api_keys_link():
    index_template = Path("app/templates/index.html").read_text(encoding="utf-8")

    # First-run blank state: warning rendered only when no models are available.
    assert "{% if not transcription_models %}" in index_template
    assert "ui.alert(level='warning', title=_('No transcription models configured')" in index_template
    # Direct navigation: "Manage API Keys" inside the sentence is the link
    # (no separate, repeated "Go to Manage API Keys" line).
    assert "id=\"emptyStateApiKeysLink\"" in index_template
    assert "_('Add a model in %(link)s to start transcribing.', link=manage_keys_link)" in index_template
    assert "Go to Manage API Keys" not in index_template
    assert "allow_api_key_management" in index_template
    # The link is wired to the existing modal opener.
    assert "window.openApiKeyModalDialog" in index_template
    # Admins without the permission get a plain "contact administrator" message.
    assert "Contact your administrator to enable them" in index_template


def test_gemini_permission_gate_present_in_transcribe_button_matrix():
    """The home transcribe-button gate must admit Gemini-permitted users.

    Regression guard: the provider->permission matrix in main_init.js
    originally had no 'gemini' branch, so selecting a Gemini model always
    disabled the button with 'Permission denied'.
    """
    script = Path("app/static/js/main_init.js").read_text(encoding="utf-8")

    matrix_line = [
        line for line in script.splitlines()
        if "selectedProvider === 'gemini'" in line
        and "use_api_google_gemini" in line
    ]
    assert matrix_line, (
        "main_init.js must grant canUseSelectedApi for gemini via "
        "permissions.use_api_google_gemini"
    )
    assert "canUseSelectedApi" in matrix_line[0]

    # Context prompts are supported for Gemini file transcription (mapped to
    # custom_vocabulary), matched via the provider (values are qualified keys).
    assert re.search(
        r"supportsContextPrompt = [^;]*\|\| selectedProvider === 'gemini'",
        script,
    ), "context-prompt gate must treat gemini as a prompt-capable provider"


def test_transcribe_button_gate_checks_daily_weekly_monthly_cost_and_minutes_limits():
    script = Path("app/static/js/main_init.js").read_text(encoding="utf-8")
    quota_utils = Path("app/static/js/quota_utils.js").read_text(encoding="utf-8")
    quota_block_start = script.index("if (!disableReason && window.IS_MULTI_USER) {")
    quota_block_end = script.index("if (!disableReason && !isFileSelected)", quota_block_start)
    quota_block = script[quota_block_start:quota_block_end]

    assert "getUsageQuotaExceededReason" in quota_block
    assert "metrics: ['cost', 'minutes']" in quota_block
    assert "blockAtCurrentLimit: true" in quota_block
    assert "['daily', 'weekly', 'monthly']" in quota_utils
    assert "limit_${period}_${metric}" in quota_utils
    assert "usage[period]" in quota_utils


def test_workflow_and_live_browser_gates_use_server_quota_reservations():
    workflow_script = Path("app/static/js/workflow_modal.js").read_text(encoding="utf-8")
    live_script = Path("app/static/js/live_transcription.js").read_text(encoding="utf-8")
    readiness_source = Path("app/api/user_settings.py").read_text(encoding="utf-8")

    assert "getUsageQuotaExceededReason" in workflow_script
    assert "{ workflows: 1 }" in workflow_script
    workflow_quota_check = workflow_script.index("const quotaReason =")
    pre_apply_branch = workflow_script.index("if (isPreApplyMode)")
    pre_apply_return = workflow_script.index(
        "closeWorkflowModalDialog();\n        return;",
        pre_apply_branch,
    )
    assert workflow_quota_check > pre_apply_return
    assert "getUsageQuotaExceededReason" in live_script
    assert "{ live_minutes: reservation }" in live_script
    assert "LIVE_MINUTES_RESERVATION" in readiness_source
    assert "'live_minutes': LIVE_MINUTES_RESERVATION" in readiness_source


def test_profile_form_default_model_selects_do_not_reject_stale_defaults():
    forms_source = Path("app/forms.py").read_text(encoding="utf-8")

    # Defaults can point at models whose key is not (yet) configured; the
    # profile form must not reject them or saving settings would break.
    assert "default_transcription_model = SelectField(" in forms_source
    assert "default_transcription_model) choices" not in forms_source
    for field in ("default_transcription_model", "default_title_generation_model", "default_workflow_model"):
        block_start = forms_source.index(f"{field} = SelectField(")
        block = forms_source[block_start:block_start + 400]
        assert "validate_choice=False" in block


def test_admin_pricing_options_keep_transcription_and_llm_records_separate(monkeypatch):
    _set_minimal_app_environment(monkeypatch)
    from app.admin_panel.routes import build_pricing_options

    with patch(
        "app.admin_panel.routes.transcription_catalog_model.get_active_models",
        return_value=[
            {
                "code": "gpt-4o-transcribe",
                "display_name": "OpenAI GPT-4o Transcribe",
                "provider_code": "openai",
                "required_api_key": "openai",
            },
            {
                "code": "universal",
                "display_name": "AssemblyAI Universal",
                "provider_code": "assemblyai",
                "required_api_key": "assemblyai",
            },
            {
                "code": "qwen/qwen3-asr-1.7b",
                "display_name": "Qwen Qwen3 ASR 1.7B",
                "provider_code": "openrouter",
                "required_api_key": "openrouter",
            },
        ],
    ), patch(
        "app.admin_panel.routes.user_service.get_aggregate_api_key_status",
        return_value={
            "openai": True,
            "provider_keys": {
                "openai": [
                    {"model_name": "OpenAI", "provider_wide": True, "model_purposes": ["transcription"]},
                ],
                "assemblyai": [
                    {"model_name": "AssemblyAI", "provider_wide": True, "model_purposes": ["transcription"]},
                ],
                "openrouter": [
                    {"model_name": "qwen/qwen3-asr-1.7b", "model_purposes": ["transcription"]},
                ],
            },
        },
    ), patch(
        "app.admin_panel.routes.transcription_catalog_model.get_live_models",
        return_value=[{"code": "gpt-live-transcribe", "display_name": "GPT Live Transcribe"}],
    ), patch(
        "app.admin_panel.routes.llm_catalog_model.get_llm_model_options",
        return_value=[
            {"code": "gemini-3.0-flash", "display_name": "Gemini 3.0 Flash"},
        ],
    ):
        options = build_pricing_options()

    # Transcription section: transcription models only (normal + live + user slugs),
    # never LLM models and never a bare provider name.
    assert "gemini-3.0-flash" not in options["transcription"]
    assert options["transcription"]["openai:gpt-4o-transcribe"] == "OpenAI GPT-4o Transcribe"
    assert options["transcription"]["assemblyai:universal"] == "AssemblyAI Universal"
    assert options["transcription"]["openrouter:qwen/qwen3-asr-1.7b"] == "Qwen Qwen3 ASR 1.7B"
    assert "AssemblyAI" not in options["transcription"]
    assert "OpenAI" not in options["transcription"]
    assert "OpenRouter" not in options["transcription"]
    assert "openrouter" not in options["transcription"]
    assert list(options["transcription"].values()) == sorted(
        options["transcription"].values(), key=str.casefold
    )
    # LLM sections receive LLM models only.
    assert options["title_generation"]["gemini-3.0-flash"] == "Gemini 3.0 Flash"
    assert options["workflow"] == options["title_generation"]
    assert "whisper" not in options["title_generation"]
    assert "qwen/qwen3-asr-1.7b" not in options["title_generation"]


def test_admin_cost_template_uses_the_same_model_option_shape_for_all_sections():
    template = Path("app/templates/admin/costs.html").read_text(encoding="utf-8")

    assert template.count("pricing_options.transcription.items()") == 1
    assert template.count("pricing_options.title_generation.items()") == 1
    assert template.count("pricing_options.workflow.items()") == 1
    assert template.count("class=\"input-select pricing-model-select\"") == 3
    assert "title_generation_models" not in template
    assert "workflow_models" not in template


def test_admin_default_model_grid_keeps_labels_on_one_line():
    template = Path("app/templates/admin/create_edit_role.html").read_text(encoding="utf-8")

    assert "lg:grid-cols-4 gap-6 items-start" in template
    assert template.count("form-label whitespace-nowrap") == 4
    assert "Default Title Generation Model" not in template


def test_admin_default_model_grid_order_matches_user_settings():
    role_template = Path("app/templates/admin/create_edit_role.html").read_text(encoding="utf-8")
    settings_template = Path("app/templates/layout/modals/profile_modal.html").read_text(encoding="utf-8")

    role_fields = [
        role_template.index("form.default_transcription_model"),
        role_template.index("form.default_live_transcription_model"),
        role_template.index("form.default_workflow_model"),
        role_template.index("form.default_title_generation_model"),
    ]
    settings_fields = [
        settings_template.index("profileDefaultModel"),
        settings_template.index("profileDefaultLiveModel"),
        settings_template.index("profileDefaultWorkflowModel"),
        settings_template.index("profileDefaultAuxiliaryModel"),
    ]

    assert role_fields == sorted(role_fields)
    assert settings_fields == sorted(settings_fields)


class _Cursor:
    def __init__(self):
        self.rows = [
            {"model_slug": "gpt-4.1"},
            {"model_slug": "openai/gpt-4.1-mini"},
            {"model_slug": ""},
        ]

    def execute(self, sql):
        self.sql = sql

    def fetchall(self):
        return self.rows


def test_saved_api_key_model_names_are_read_from_model_slug_column(monkeypatch):
    _set_minimal_app_environment(monkeypatch)
    from app.models import user_api_key

    cursor = _Cursor()
    with patch.object(user_api_key, "get_cursor", return_value=cursor):
        names = user_api_key.get_distinct_model_names()

    assert names == ["gpt-4.1", "openai/gpt-4.1-mini"]
    assert "model_slug" in cursor.sql
    assert "DISTINCT" in cursor.sql


def test_admin_pricing_route_only_passes_the_canonical_options_context():
    route_source = Path("app/admin_panel/routes.py").read_text(encoding="utf-8")

    assert "pricing_options = build_pricing_options()" in route_source
    assert "transcription_models=transcription_models" not in route_source
    assert "title_generation_models=title_generation_models" not in route_source
    assert "workflow_models=workflow_models" not in route_source


def test_live_purpose_keeps_the_entered_model_name():
    script = Path("app/static/js/user_settings.js").read_text(encoding="utf-8")

    assert "const purpose = document.querySelector('input[name=\"model_purpose\"]:checked')?.value || 'transcription';" in script
    assert "modelNameInput.value = liveModelSelect.value" not in script
    assert "formData.set('model_purpose', purpose);" in script
    assert "formData.set('model_name', modelName);" in script


def test_api_key_entries_render_explicit_model_purpose_badges():
    template = Path("app/templates/layout/modals/api_key_modal.html").read_text(encoding="utf-8")
    script = Path("app/static/js/user_settings.js").read_text(encoding="utf-8")
    service = Path("app/services/user_service.py").read_text(encoding="utf-8")

    assert "MODEL_PURPOSE_LABELS" in script
    # Lilac design language: purpose tags are small tonal (lilac) badges.
    assert "badge badge-primary" in script
    assert "badge.textContent = label" in script
    assert "textContent = `[${label}]`" not in script
    assert "model_purposes" in service
    # The inline selection preview was removed; badges remain for configured keys.
    assert "modelPurposePreview" not in template


def test_api_key_modal_uses_provider_specific_model_help_and_mobile_purpose_layout():
    template = Path("app/templates/layout/modals/api_key_modal.html").read_text(encoding="utf-8")
    script = Path("app/static/js/user_settings.js").read_text(encoding="utf-8")

    assert 'id="modelNameHint"' in template
    assert "Enter the OpenAI model name only, without the vendor prefix." in script
    assert "Enter the Google model name only, without the vendor prefix." in script
    assert "Enter the OpenRouter model as vendor/model." in script
    # Segmented control: stacks on mobile, three columns from sm.
    assert "grid grid-cols-1 gap-1 rounded-xl bg-surface-muted p-1 sm:grid-cols-3" in template
    assert "Usage tags:" not in template
    assert "Choose whether this model should handle" not in template
    assert "Use the provider model name" not in template


def test_transcription_selectors_dedupe_catalog_codes():
    index_template = Path("app/templates/index.html").read_text(encoding="utf-8")
    profile_script = Path("app/static/js/profile.js").read_text(encoding="utf-8")
    catalog = Path("app/models/transcription_catalog.py").read_text(encoding="utf-8")

    # Selectors dedupe by (code, openrouter slug) so every OpenRouter
    # transcription model renders as its own option instead of collapsing.
    assert "seen_transcription_models = namespace(keys=[])" in index_template
    assert "option_key = model.model_key or model.code" in index_template
    assert "const modelKey = model.model_key || model.code;" in profile_script
    assert "openrouter:${model.model_name || model.model_slug || ''}" not in profile_script
    assert "seen_keys: set[str] = set()" in catalog
    assert "def build_model_options(" in catalog
    assert "get_live_models" in catalog


def test_pricing_model_keys_are_not_rewritten_to_provider_names():
    pricing_model = Path("app/models/pricing.py").read_text(encoding="utf-8")

    assert "cursor.execute(sql, (item_type, str(item_key).strip(), price))" in pricing_model
    assert "item_key.lower()" not in pricing_model
    assert "item_key.upper()" not in pricing_model
    assert "TITLE_GENERATION_LLM_PROVIDER" not in pricing_model
    assert "WORKFLOW_LLM_PROVIDER" not in pricing_model


def test_pricing_fallbacks_use_model_defaults_not_provider_names():
    pricing_service = Path("app/services/pricing_service.py").read_text(encoding="utf-8")

    assert "TITLE_GENERATION_LLM_MODEL" in pricing_service
    assert "WORKFLOW_LLM_MODEL" in pricing_service
    assert "TITLE_GENERATION_LLM_PROVIDER" not in pricing_service
    assert "WORKFLOW_LLM_PROVIDER" not in pricing_service


def test_expand_models_skips_generic_openrouter_when_no_slug_is_known():
    from app.models import transcription_catalog

    models = [
        {"code": "whisper", "display_name": "OpenAI Whisper", "permission_key": None, "required_api_key": "openai"},
        {"code": "openrouter", "display_name": "OpenRouter", "permission_key": None, "required_api_key": "openrouter"},
    ]

    expanded = transcription_catalog.expand_models_for_ui(models, {"openai": True})

    assert expanded == []
    assert all(model["code"] != "openrouter" for model in expanded)


def test_provider_wide_key_unlocks_all_models_for_that_provider():
    from app.models import transcription_catalog

    models = [
        {
            "code": "gpt-4o-transcribe",
            "display_name": "OpenAI GPT-4o Transcribe",
            "provider_code": "openai",
            "permission_key": None,
            "required_api_key": "openai",
        },
        {
            "code": "universal",
            "display_name": "AssemblyAI Universal",
            "provider_code": "assemblyai",
            "permission_key": None,
            "required_api_key": "assemblyai",
        },
    ]

    expanded = transcription_catalog.expand_models_for_ui(
        models,
        {
            "provider_keys": {
                "openai": [
                    {"model_name": "OpenAI", "provider_wide": True, "model_purposes": ["transcription"]},
                ],
                "assemblyai": [
                    {"model_name": "AssemblyAI", "provider_wide": True, "model_purposes": ["transcription"]},
                ],
            },
        },
    )

    assert [model["code"] for model in expanded] == [
        "gpt-4o-transcribe",
        "universal",
    ]


def test_single_user_provider_boolean_unlocks_catalog_models():
    from app.models import transcription_catalog

    models = [
        {
            "code": "gpt-4o-transcribe",
            "display_name": "OpenAI GPT-4o Transcribe",
            "provider_code": "openai",
            "required_api_key": "openai",
        },
        {
            "code": "universal",
            "display_name": "AssemblyAI Universal",
            "provider_code": "assemblyai",
            "required_api_key": "assemblyai",
        },
    ]

    expanded = transcription_catalog.expand_models_for_ui(
        models,
        {"openai": True, "assemblyai": True},
    )

    assert [model["code"] for model in expanded] == [
        "gpt-4o-transcribe",
        "universal",
    ]


def test_expand_models_returns_empty_when_no_provider_key_exists():
    from app.models import transcription_catalog

    models = [
        {"code": "whisper", "display_name": "OpenAI Whisper", "permission_key": None, "required_api_key": "openai"},
        {"code": "gpt-4o-transcribe", "display_name": "OpenAI GPT-4o Transcribe", "permission_key": None, "required_api_key": "openai"},
        {"code": "openrouter", "display_name": "OpenRouter", "permission_key": None, "required_api_key": "openrouter"},
    ]

    expanded = transcription_catalog.expand_models_for_ui(models, {})

    assert expanded == []


def test_models_without_required_api_keys_remain_available():
    from app.models import transcription_catalog

    models = [
        {"code": "local-model", "display_name": "Local Model", "permission_key": None, "required_api_key": None},
        {"code": "whisper", "display_name": "OpenAI Whisper", "permission_key": None, "required_api_key": "openai"},
    ]

    expanded = transcription_catalog.expand_models_for_ui(models, {})

    assert [model["code"] for model in expanded] == ["local-model"]


def test_expand_models_does_not_turn_provider_anchor_into_a_model():
    from app.models import transcription_catalog

    models = [
        {"code": "openrouter", "display_name": "OpenRouter", "permission_key": None, "required_api_key": "openrouter"},
    ]

    expanded = transcription_catalog.expand_models_for_ui(
        models,
        {"provider_keys": {"openrouter": [
            {"model_name": "x-ai/grok-stt-1.0", "model_purposes": ["transcription"]},
        ]}},
    )

    assert expanded == []


def test_dynamic_openrouter_model_row_is_selectable_without_provider_anchor():
    from app.models import transcription_catalog

    models = [
        {
            "code": "x-ai/grok-stt-1.0",
            "display_name": "xAI Grok STT 1.0",
            "provider_code": "openrouter",
            "permission_key": None,
            "required_api_key": "openrouter",
        },
    ]

    expanded = transcription_catalog.expand_models_for_ui(
        models,
        {"provider_keys": {"openrouter": [
            {"model_name": "x-ai/grok-stt-1.0", "model_purposes": ["transcription"]},
        ]}},
    )

    assert [(model["code"], model.get("model_name")) for model in expanded] == [
        ("x-ai/grok-stt-1.0", "x-ai/grok-stt-1.0"),
    ]


def test_build_model_options_sorts_all_provider_models_by_display_name():
    from app.models import transcription_catalog

    models = [
        {
            "code": "gpt-4o-transcribe",
            "display_name": "OpenAI GPT-4o Transcribe",
            "provider_code": "openai",
            "permission_key": None,
            "required_api_key": "openai",
        },
        {
            "code": "universal",
            "display_name": "AssemblyAI Universal",
            "provider_code": "assemblyai",
            "permission_key": None,
            "required_api_key": "assemblyai",
        },
        {
            "code": "x-ai/grok-stt-1.0",
            "display_name": "xAI Grok STT 1.0",
            "provider_code": "openrouter",
            "permission_key": None,
            "required_api_key": "openrouter",
        },
        {
            "code": "qwen/qwen3-asr-1.7b",
            "display_name": "Qwen Qwen3 ASR 1.7B",
            "provider_code": "openrouter",
            "permission_key": None,
            "required_api_key": "openrouter",
        },
        {
            "code": "openrouter",
            "display_name": "OpenRouter",
            "provider_code": "openrouter",
            "permission_key": None,
            "required_api_key": "openrouter",
        },
    ]
    status = {
        "provider_keys": {
            "openai": [
                {"model_name": "OpenAI", "provider_wide": True, "model_purposes": ["transcription"]},
            ],
            "assemblyai": [
                {"model_name": "AssemblyAI", "provider_wide": True, "model_purposes": ["transcription"]},
            ],
            "openrouter": [
                {"model_name": "x-ai/grok-stt-1.0", "model_purposes": ["transcription"]},
                {"model_name": "qwen/qwen3-asr-1.7b", "model_purposes": ["transcription"]},
            ],
        },
    }

    options = transcription_catalog.build_model_options(models, status)

    assert [(m["code"], m.get("model_name")) for m in options] == [
        ("universal", "universal"),
        ("gpt-4o-transcribe", "gpt-4o-transcribe"),
        ("qwen/qwen3-asr-1.7b", "qwen/qwen3-asr-1.7b"),
        ("x-ai/grok-stt-1.0", "x-ai/grok-stt-1.0"),
    ]
    assert all(
        option["display_name"] not in {"OpenAI", "AssemblyAI", "OpenRouter"}
        for option in options
    )


def test_llm_model_options_merge_user_added_llm_slugs(monkeypatch):
    _set_minimal_app_environment(monkeypatch)
    from app.models import llm_catalog

    with patch(
        "app.models.llm_catalog.get_active_models",
        return_value=[{"code": "gemini-3.0-flash", "display_name": "Gemini 3.0 Flash"}],
    ):
        options = llm_catalog.get_llm_model_options(
            {
                "provider_keys": {
                    "gemini": [
                        {"model_name": "gemini-2.5-pro", "model_purposes": ["llm"]},
                        {"model_name": "Google", "model_purposes": ["llm"], "provider_wide": True},
                    ],
                    "openrouter": [
                        {"model_name": "openai/gpt-4.1-mini", "model_purposes": ["llm"]},
                        {"model_name": "nvidia/llama-3.1", "model_purposes": ["transcription"]},
                    ],
                },
            }
        )

    assert [(m["code"], m.get("required_api_key")) for m in options] == [
        ("gemini-3.0-flash", None),
        ("gemini-2.5-pro", "gemini"),
        ("openai/gpt-4.1-mini", "openrouter"),
    ]


def test_effective_key_status_aggregates_for_admins_but_not_users(monkeypatch):
    _set_minimal_app_environment(monkeypatch)
    from app.services import user_service

    admin = SimpleNamespace(id=1, role=SimpleNamespace(access_admin_panel=True))
    regular = SimpleNamespace(
        id=2,
        role=SimpleNamespace(access_admin_panel=False, allow_api_key_management=False),
    )
    key_manager = SimpleNamespace(
        id=3,
        role=SimpleNamespace(access_admin_panel=False, allow_api_key_management=True),
    )
    with patch.object(
        user_service, "get_aggregate_api_key_status", return_value={"aggregated": True}
    ) as aggregate, patch.object(
        user_service, "get_admin_api_key_status", return_value={"admin_configured": True}
    ) as admin_configured, patch.object(
        user_service, "get_user_api_key_status", return_value={"own": True}
    ) as own:
        assert user_service.get_effective_key_status(admin) == {"aggregated": True}
        assert user_service.get_effective_key_status(regular) == {
            "admin_configured": True,
            "own": True,
        }
        assert user_service.get_effective_key_status(key_manager) == {
            "admin_configured": True,
            "own": True,
        }
        aggregate.assert_called_once_with()
        assert admin_configured.call_count == 2
        assert own.call_args_list[0].args == (2,)
        assert own.call_args_list[1].args == (3,)


def test_all_jinja_templates_parse_without_escaping_artifacts():
    """Every template must compile under Jinja2.

    Guards against raw JSON-style escaped quotes (\\") being written into
    templates (previously broke forgot_password.html at parse time).
    """
    import re

    from jinja2 import Environment

    env = Environment()
    templates = sorted(Path("app/templates").rglob("*.html"))
    assert templates, "no templates found"
    for path in templates:
        source = path.read_text(encoding="utf-8")
        env.parse(source)  # raises TemplateSyntaxError on invalid syntax
        # No stray JSON-escape backslashes before quotes may appear anywhere
        # (they are both a Jinja parse hazard and invalid HTML).
        assert not re.search(r"\\\"", source), f"escaped-quote artifact in {path}"


def test_providers_are_fixed_and_models_are_never_provider_labels(monkeypatch):
    """Model dropdowns must expose models, not provider labels.

    After the display-name rework the legacy API_PROVIDER_NAME_MAP is gone:
    models are registered at runtime from saved keys with the raw model name
    as display name, and the provider list is fixed to the four transcription
    backends. Regression guard: no provider label may leak in as a model's
    display name, and providers are never treated as pre-seeded models.
    """
    _set_minimal_app_environment(monkeypatch)
    from app.config import Config

    # The legacy provider-label map is removed entirely.
    assert not hasattr(Config, "API_PROVIDER_NAME_MAP")

    # Providers are fixed and seeded; models are NOT (no whisper/gpt-4o codes).
    assert Config.TRANSCRIPTION_PROVIDERS == ["assemblyai", "openai", "gemini", "openrouter"]

    # Provider display names belong to provider metadata only. They are not
    # emitted by the shared model-option builder as selectable model rows.
    from app.models import transcription_catalog
    assert set(transcription_catalog._PROVIDER_METADATA) == {
        "assemblyai",
        "openai",
        "openrouter",
        "gemini",
    }
    assert {
        meta["display_name"]
        for meta in transcription_catalog._PROVIDER_METADATA.values()
    } == {"AssemblyAI", "OpenAI", "OpenRouter", "Google"}


def test_key_save_and_delete_refresh_the_model_catalog_globals():
    script = Path("app/static/js/user_settings.js").read_text(encoding="utf-8")

    assert "fetch('/api/user/model-catalog'" in script
    assert "window.TRANSCRIPTION_MODELS = data.transcription" in script
    assert "window.LIVE_TRANSCRIPTION_MODELS = data.live" in script
    assert "window.LLM_MODEL_CATALOG = data.llm" in script
    # Both mutating flows must refresh the globals, chained after the
    # key-status refetch.
    assert script.count("return fetchApiKeyStatus()\n            .then(() => refreshModelCatalogGlobals());") == 2
