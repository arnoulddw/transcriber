import ast
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from flask import Flask

# This worktree intentionally does not carry a deployment .env file. Supply
# the minimum import-time settings needed by app.config for these unit tests.
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DEPLOYMENT_MODE", "single")
os.environ.setdefault("MYSQL_USER", "test-user")
os.environ.setdefault("MYSQL_PASSWORD", "test-password")
os.environ.setdefault("MYSQL_DB", "test-db")

from app.tasks import cleanup
from migrations import runner
import app.initialization as initialization


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_cleanup_once_runs_all_retention_stages(monkeypatch, tmp_path):
    app = Flask(__name__)
    app.config.update(
        TEMP_UPLOADS_DIR=str(tmp_path),
        DELETE_THRESHOLD=123,
        PHYSICAL_DELETION_DAYS=45,
    )
    calls = []

    monkeypatch.setattr(
        cleanup.file_service,
        "cleanup_old_files",
        lambda directory, threshold, *, protected_paths: calls.append(
            ("files", directory, threshold, protected_paths)
        ) or 2,
    )
    monkeypatch.setattr(
        cleanup.background_job_model,
        "get_active_transcription_file_paths",
        lambda: {"/uploads/queued.wav"},
    )
    monkeypatch.setattr(cleanup.user_model, "get_all_users", lambda: [])
    monkeypatch.setattr(
        cleanup.transcription_utils,
        "physically_delete_hidden_records",
        lambda days: calls.append(("hidden", days)) or 1,
    )
    monkeypatch.setattr(
        cleanup.llm_operation_model,
        "delete_orphaned_llm_operations",
        lambda days: calls.append(("orphans", days)) or 3,
    )
    monkeypatch.setattr(
        cleanup.live_session_model,
        "purge_expired_sessions",
        lambda: calls.append(("live_sessions",)) or 4,
    )

    cleanup.run_cleanup_once(app)

    assert calls == [
        ("files", str(tmp_path), 123, {"/uploads/queued.wav"}),
        ("hidden", 45),
        ("orphans", 45),
        ("live_sessions",),
    ]


def test_file_cleanup_keeps_old_audio_needed_by_pending_job(tmp_path):
    protected = tmp_path / "pending.wav"
    orphan = tmp_path / "orphan.wav"
    protected.write_bytes(b"pending")
    orphan.write_bytes(b"orphan")
    old_time = time.time() - 200
    os.utime(protected, (old_time, old_time))
    os.utime(orphan, (old_time, old_time))

    deleted = cleanup.file_service.cleanup_old_files(
        str(tmp_path), 100, protected_paths={str(protected)}
    )

    assert deleted == 1
    assert protected.exists()
    assert not orphan.exists()


def test_web_factory_does_not_start_cleanup_thread():
    source = (PROJECT_ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert not any(
        isinstance(node, ast.Name) and node.id == "run_cleanup_task"
        for node in ast.walk(tree)
    )


def test_migration_runner_propagates_connection_failure(monkeypatch):
    failure = RuntimeError("database unavailable")
    monkeypatch.setattr(runner, "get_db", lambda: (_ for _ in ()).throw(failure))

    with pytest.raises(RuntimeError, match="database unavailable"):
        runner.run_migrations()


def test_schema_presence_gate_checks_only_the_baseline_sentinel(monkeypatch):
    cursor = Mock()
    cursor.fetchone.return_value = {"Tables_in_test_db (roles)": "roles"}
    monkeypatch.setattr(initialization, "get_cursor", lambda: cursor)

    assert initialization.database_has_application_schema() is True
    cursor.execute.assert_called_once_with("SHOW TABLES LIKE %s", ("roles",))
    cursor.fetchall.assert_called_once_with()


def test_existing_schema_skips_all_model_initializers(monkeypatch):
    monkeypatch.setattr(initialization, "database_has_application_schema", lambda: True)
    initializer = Mock()
    monkeypatch.setattr(initialization.role_model, "init_roles_table", initializer)
    monkeypatch.setattr(initialization.user_model, "init_db_command", initializer)
    monkeypatch.setattr(initialization.background_job_model, "init_db_command", initializer)

    initialization.initialize_database_schema(create_roles=False)

    initializer.assert_not_called()


def test_empty_database_uses_model_baseline_initializers(monkeypatch):
    monkeypatch.setattr(initialization, "database_has_application_schema", lambda: False)
    calls = []

    monkeypatch.setattr(initialization.role_model, "init_roles_table", lambda: calls.append("roles"))
    monkeypatch.setattr(initialization.user_model, "init_db_command", lambda: calls.append("users"))
    monkeypatch.setattr(initialization.user_api_key_model, "init_db_command", lambda: calls.append("user_api_keys"))
    monkeypatch.setattr(initialization.public_api_key_model, "init_db_command", lambda: calls.append("public_api_keys"))
    monkeypatch.setattr(initialization.transcription_model, "init_db_command", lambda: calls.append("transcriptions"))
    monkeypatch.setattr(initialization.transcription_job_lease_model, "init_db_command", lambda: calls.append("leases"))
    monkeypatch.setattr(initialization.live_session_model, "init_db_command", lambda: calls.append("live_sessions"))
    monkeypatch.setattr(initialization.template_prompt_model, "init_db_command", lambda: calls.append("templates"))
    monkeypatch.setattr(initialization.user_prompt_model, "init_db_command", lambda: calls.append("user_prompts"))
    monkeypatch.setattr(initialization.llm_operation_model, "init_db_command", lambda: calls.append("llm_operations"))
    monkeypatch.setattr(initialization.pricing_model, "init_db_command", lambda: calls.append("pricing"))
    monkeypatch.setattr(initialization.transcription_catalog_model, "init_db_command", lambda: calls.append("transcription_catalog"))
    monkeypatch.setattr(initialization.llm_catalog_model, "init_db_command", lambda: calls.append("llm_catalog"))
    monkeypatch.setattr(initialization.background_job_model, "init_db_command", lambda: calls.append("background_jobs"))
    monkeypatch.setattr(initialization.role_model, "init_user_usage_table", lambda: calls.append("user_usage"))
    monkeypatch.setattr(initialization.app_settings_model, "init_db_command", lambda: calls.append("app_settings"))

    initialization.initialize_database_schema(create_roles=False)

    assert calls == [
        "roles",
        "users",
        "user_api_keys",
        "public_api_keys",
        "transcriptions",
        "leases",
        "live_sessions",
        "background_jobs",
        "templates",
        "user_prompts",
        "llm_operations",
        "pricing",
        "transcription_catalog",
        "llm_catalog",
        "user_usage",
        "app_settings",
    ]


def test_legacy_api_key_drop_is_owned_by_versioned_migration():
    user_schema = (PROJECT_ROOT / "app" / "models" / "user" / "schema.py").read_text(
        encoding="utf-8"
    )
    migration = (
        PROJECT_ROOT / "migrations" / "V20251122_0005__migrate_user_api_keys.py"
    ).read_text(encoding="utf-8")

    assert "DROP COLUMN api_keys_encrypted" not in user_schema
    assert "ALTER TABLE users DROP COLUMN api_keys_encrypted" in migration


def _config_environment(**overrides):
    environment = os.environ.copy()
    environment.update(
        {
            "SECRET_KEY": "test-secret",
            "DEPLOYMENT_MODE": "single",
            "MYSQL_USER": "test-user",
            "MYSQL_PASSWORD": "test-password",
            "MYSQL_DB": "test-db",
            "TRANSCRIPTION_PROVIDERS": "openai,gemini,openrouter,assemblyai",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    environment.update(overrides)
    return environment


def test_config_honors_log_level_and_default_llm_provider():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.config import Config; print(Config.LOG_LEVEL); "
            "print(Config.DEFAULT_LLM_PROVIDER); print(Config.LLM_PROVIDER)",
        ],
        cwd=PROJECT_ROOT,
        env=_config_environment(
            LOG_LEVEL="warning",
            DEFAULT_LLM_PROVIDER="openrouter",
            LLM_PROVIDER="GEMINI",
        ),
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines()[-3:] == ["WARNING", "OPENROUTER", "OPENROUTER"]


def test_config_keeps_legacy_llm_provider_environment_as_fallback():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.config import Config; print(Config.DEFAULT_LLM_PROVIDER)",
        ],
        cwd=PROJECT_ROOT,
        env=_config_environment(LLM_PROVIDER="OPENAI"),
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip().splitlines()[-1] == "OPENAI"
