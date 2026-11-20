import os

from app.config import _resolve_secret_key


def test_env_secret_key_wins_and_writes_nothing(tmp_path, monkeypatch):
    key_file = tmp_path / "runtime" / "secret_key"
    monkeypatch.setenv("SECRET_KEY", "from-env")

    assert _resolve_secret_key(str(key_file)) == "from-env"
    assert not key_file.exists()


def test_missing_secret_key_is_generated_once_and_reused(tmp_path, monkeypatch):
    key_file = tmp_path / "runtime" / "secret_key"
    monkeypatch.setenv("SECRET_KEY", "  ")

    first = _resolve_secret_key(str(key_file))
    second = _resolve_secret_key(str(key_file))

    assert len(first) == 64
    assert second == first
    assert key_file.read_text().strip() == first
    assert oct(os.stat(key_file).st_mode & 0o777) == "0o600"
    assert [p.name for p in key_file.parent.iterdir()] == ["secret_key"]


def test_existing_key_file_is_used(tmp_path, monkeypatch):
    key_file = tmp_path / "secret_key"
    key_file.write_text("kept-from-last-start\n")
    monkeypatch.delenv("SECRET_KEY", raising=False)

    assert _resolve_secret_key(str(key_file)) == "kept-from-last-start"
