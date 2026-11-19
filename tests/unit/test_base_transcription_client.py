import logging
import threading
from typing import Any, Dict, Optional, Tuple
from unittest.mock import Mock, patch

import pytest

from app.services import file_service
from app.services.api_clients import get_transcription_client
from app.services.api_clients.exceptions import TranscriptionProcessingError
from app.services.api_clients.transcription.assemblyai import AssemblyAITranscriptionAPI
from app.services.api_clients.transcription.base_transcription_client import (
    BaseTranscriptionClient,
)


class StubTranscriptionClient(BaseTranscriptionClient):
    CATALOG_MODEL_CODE = "stub"

    def __init__(self, chunk_results):
        self.chunk_results = chunk_results
        self.progress_messages = []
        self.has_transcription_warning = False
        super().__init__("test-key", {"TRANSCRIPTION_WORKERS": 2})
        self.cancel_event = threading.Event()
        self.progress_callback = self._collect_progress

    def _collect_progress(self, message, is_error=False):
        self.progress_messages.append((message, is_error))

    def _initialize_client(self, api_key):
        pass

    def _prepare_api_params(
        self,
        language_code: str,
        context_prompt: str,
        response_format: str,
        is_chunk: bool,
        extra_options: Optional[Dict[str, Any]] = None,
    ):
        return {}

    def _call_api(self, file_handle, api_params):
        return None

    def _process_response(self, response, response_format) -> Tuple[str, Optional[str]]:
        return "", None

    def _get_retryable_errors(self):
        return ()

    def _get_api_name(self):
        return "Stub Transcription"

    def _transcribe_single_chunk_with_retry(
        self,
        chunk_path: str,
        idx: int,
        total_chunks: int,
        language_code: str,
        response_format: str,
        context_prompt: str = "",
        log_prefix: str = "",
        max_retries: int = 3,
        extra_options: Optional[Dict[str, Any]] = None,
    ):
        return self.chunk_results[idx]


def _make_chunks(tmp_path, count, *, non_empty=True):
    chunks = []
    for index in range(1, count + 1):
        chunk = tmp_path / f"chunk_{index:03d}.mp3"
        chunk.write_bytes(b"audio" if non_empty else b"")
        chunks.append(str(chunk))
    return chunks


def _run_split(client, chunk_files):
    with patch(
        "app.services.api_clients.transcription.base_transcription_client.file_service.split_audio_file",
        return_value=chunk_files,
    ):
        return client._split_and_transcribe(
            "/tmp/source.mp3",
            "en",
            display_filename="source.mp3",
        )


def test_split_and_transcribe_fails_when_a_chunk_result_is_missing(tmp_path):
    chunk_files = _make_chunks(tmp_path, 2)
    client = StubTranscriptionClient({1: ("First chunk", None), 2: None})

    with pytest.raises(TranscriptionProcessingError, match="did not return a transcription result"):
        _run_split(client, chunk_files)


def test_split_and_transcribe_aggregates_all_chunk_results_in_order(tmp_path):
    chunk_files = _make_chunks(tmp_path, 3)
    client = StubTranscriptionClient({
        1: ("First chunk", None),
        2: ("Second chunk", None),
        3: ("Third chunk", None),
    })

    result = _run_split(client, chunk_files)

    assert result == ("First chunk Second chunk Third chunk", "en")
    assert client.has_transcription_warning is False


def test_split_and_transcribe_warns_for_empty_text_from_non_trivial_chunk(tmp_path, caplog):
    chunk_files = _make_chunks(tmp_path, 2)
    client = StubTranscriptionClient({1: ("First chunk", None), 2: ("  ", None)})

    with caplog.at_level(logging.WARNING):
        result = _run_split(client, chunk_files)

    assert result == ("First chunk", "en")
    assert client.has_transcription_warning is True
    assert client.transcription_warning_detail == {"empty_chunks": [2], "total_chunks": 2}
    assert any("Chunk 2/2 returned no transcription text" in record.message for record in caplog.records)
    assert any(
        not is_error and "Chunk 2/2 returned no transcription text" in message
        for message, is_error in client.progress_messages
    )


def test_split_and_transcribe_does_not_warn_for_empty_source_chunk(tmp_path, caplog):
    chunk_files = _make_chunks(tmp_path, 1, non_empty=False)
    client = StubTranscriptionClient({1: ("", None)})

    with caplog.at_level(logging.WARNING):
        result = _run_split(client, chunk_files)

    assert result == ("", "en")
    assert client.has_transcription_warning is False
    assert not any("returned no transcription text" in record.message for record in caplog.records)


def test_audio_format_restrictions_are_unknown_by_default():
    client = StubTranscriptionClient({1: ("", None)})

    assert client.supported_audio_formats is None
    assert client._get_transcode_target("/tmp/recording.m4a") is None


def test_supported_input_bypasses_transcoding_for_any_provider(tmp_path):
    client = StubTranscriptionClient({})
    client.supported_audio_formats = frozenset({"mp3", "wav"})
    source = tmp_path / "recording.wav"
    source.write_bytes(b"audio")
    client._call_api = Mock(return_value=object())

    with patch.object(file_service, "transcode_audio_file") as transcode:
        result = client.transcribe(str(source), "en", audio_length_seconds=30)

    assert result == ("", "en")
    transcode.assert_not_called()
    client._call_api.assert_called_once()


def test_post_transcode_size_independently_triggers_splitting(tmp_path):
    client = StubTranscriptionClient({})
    client.supported_audio_formats = frozenset({"mp3"})
    client.SPLIT_THRESHOLD_BYTES = 5
    source = tmp_path / "recording.m4a"
    source.write_bytes(b"a")
    transcoded = tmp_path / "recording_transcoded.mp3"
    transcoded.write_bytes(b"larger")
    client._split_and_transcribe = Mock(return_value=("Transcript", "en"))

    with patch.object(
        file_service, "transcode_audio_file", return_value=str(transcoded)
    ) as transcode, patch.object(
        file_service, "get_audio_duration", return_value=(30, 0.5)
    ):
        result = client.transcribe(str(source), "en", audio_length_seconds=30)

    assert result == ("Transcript", "en")
    transcode.assert_called_once()
    client._split_and_transcribe.assert_called_once_with(
        str(transcoded), "en", "", "recording.m4a", extra_options=None
    )
    assert not transcoded.exists()


def test_transcoded_file_is_cleaned_when_provider_call_fails(tmp_path):
    client = StubTranscriptionClient({})
    client.supported_audio_formats = frozenset({"mp3"})
    source = tmp_path / "recording.m4a"
    source.write_bytes(b"audio")
    transcoded = tmp_path / "recording_transcoded.mp3"
    transcoded.write_bytes(b"converted")
    client._call_api = Mock(
        side_effect=TranscriptionProcessingError("provider failed", provider="Stub")
    )

    with patch.object(
        file_service, "transcode_audio_file", return_value=str(transcoded)
    ), patch.object(file_service, "get_audio_duration", return_value=(30, 0.5)):
        with pytest.raises(TranscriptionProcessingError, match="provider failed"):
            client.transcribe(str(source), "en", audio_length_seconds=30)

    assert not transcoded.exists()


def test_conversion_failure_preserves_original_and_raises_processing_error(tmp_path):
    client = StubTranscriptionClient({})
    client.supported_audio_formats = frozenset({"mp3"})
    source = tmp_path / "recording.m4a"
    source.write_bytes(b"original")

    with patch.object(file_service, "transcode_audio_file", return_value=None):
        with pytest.raises(TranscriptionProcessingError, match="Failed to convert"):
            client.transcribe(str(source), "en", audio_length_seconds=30)

    assert source.read_bytes() == b"original"


def test_transcoded_file_is_cleaned_when_api_call_is_cancelled(tmp_path):
    client = StubTranscriptionClient({})
    client.supported_audio_formats = frozenset({"mp3"})
    source = tmp_path / "recording.m4a"
    source.write_bytes(b"audio")
    transcoded = tmp_path / "recording_transcoded.mp3"
    transcoded.write_bytes(b"converted")
    client._call_api = Mock(side_effect=InterruptedError("cancelled"))

    with patch.object(
        file_service, "transcode_audio_file", return_value=str(transcoded)
    ), patch.object(file_service, "get_audio_duration", return_value=(30, 0.5)):
        with pytest.raises(InterruptedError, match="cancelled"):
            client.transcribe(str(source), "en", audio_length_seconds=30)

    assert not transcoded.exists()


# --- split-limit resolution ---


def _stub_with_limits(config):
    client = StubTranscriptionClient({1: ("", None)})
    client.config = config
    return client


def test_model_row_wins_over_provider_row():
    limits = {"duration_s": 420, "size_mb": 25}
    client = _stub_with_limits({
        "API_LIMITS": {"gpt-4o-transcribe": limits},
        "API_PROVIDER_LIMITS": {"openai": {"duration_s": None, "size_mb": 25}},
    })
    assert client._resolve_split_limits("gpt-4o-transcribe", "openai") == limits


def test_provider_fallback_used_when_no_model_row():
    provider_row = {"duration_s": 3300, "size_mb": None}
    client = _stub_with_limits({
        "API_PROVIDER_LIMITS": {"gemini": provider_row},
    })
    # A future Gemini model with no API_LIMITS row of its own.
    assert client._resolve_split_limits("gemini-9-future", "gemini") == provider_row


def test_unknown_model_and_provider_return_empty_dict():
    client = _stub_with_limits({"API_LIMITS": {"whisper": {"size_mb": 25}}})
    assert client._resolve_split_limits("unknown-model", "mystery-provider") == {}


def test_missing_limit_dicts_tolerated():
    client = _stub_with_limits({})
    assert client._resolve_split_limits(None, "openai") == {}


def test_provider_lookup_is_case_insensitive():
    provider_row = {"duration_s": None, "size_mb": 25}
    client = _stub_with_limits({
        "API_PROVIDER_LIMITS": {"openrouter": provider_row},
    })
    assert client._resolve_split_limits("vendor/model-x", " OpenRouter ") == provider_row


# --- future AssemblyAI model names work via provider fallback limits ---


def _assemblyai_future_config():
    return {
        "API_PROVIDER_LIMITS": {"assemblyai": {"duration_s": None, "size_mb": None}},
        "TRANSCRIPTION_WORKERS": 1,
    }


def test_assemblyai_future_model_passes_catalog_code():
    """A model code never seen before is passed verbatim to the API."""
    with patch.object(AssemblyAITranscriptionAPI, "_initialize_client", return_value=None):
        client = AssemblyAITranscriptionAPI(
            "aai-key", _assemblyai_future_config(), model_code="universal-3"
        )

    assert client.CATALOG_MODEL_CODE == "universal-3"

    params = client._prepare_api_params(
        language_code="auto",
        context_prompt="",
        response_format="json",
        is_chunk=False,
    )
    assert params["speech_models"] == ["universal-3"]

    # Limits came from the assemblyai PROVIDER fallback: no duration rule and
    # no size row, so the adapter's 1 GB safety ceiling applies.
    assert client.SPLIT_THRESHOLD_SECONDS is None
    assert client.SPLIT_THRESHOLD_BYTES == 1024 * 1024 * 1024


def test_factory_routes_qualified_assemblyai_future_model():
    """get_transcription_client resolves 'assemblyai:universal-3' to the adapter."""
    config = dict(_assemblyai_future_config(), TRANSCRIPTION_WORKERS=1)
    with patch.object(AssemblyAITranscriptionAPI, "_initialize_client", return_value=None):
        client = get_transcription_client("assemblyai:universal-3", "aai-key", config)

    assert isinstance(client, AssemblyAITranscriptionAPI)
    assert client.model_code == "universal-3"
    assert client.CATALOG_MODEL_CODE == "universal-3"
