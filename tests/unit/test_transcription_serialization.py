from app.models.transcription.serialization import _map_row_to_transcription_dict


def test_transcription_warning_defaults_to_false_for_legacy_row():
    row = {
        "id": "legacy-job",
        "progress_log": [],
    }

    mapped = _map_row_to_transcription_dict(row)

    assert mapped is not None
    assert mapped["has_transcription_warning"] is False


def test_transcription_warning_is_normalized_to_boolean():
    row = {
        "id": "warned-job",
        "progress_log": [],
        "has_transcription_warning": 1,
    }

    mapped = _map_row_to_transcription_dict(row)

    assert mapped is not None
    assert mapped["has_transcription_warning"] is True


def test_transcription_warning_message_names_the_silent_last_chunk():
    mapped = _map_row_to_transcription_dict({
        "id": "warned-job",
        "progress_log": [],
        "has_transcription_warning": 1,
        "transcription_warning_detail": '{"empty_chunks": [5], "total_chunks": 5}',
    })

    assert "last audio chunk (5 of 5)" in mapped["transcription_warning_message"]


def test_transcription_warning_message_counts_several_empty_chunks():
    mapped = _map_row_to_transcription_dict({
        "id": "warned-job",
        "progress_log": [],
        "has_transcription_warning": 1,
        "transcription_warning_detail": {"empty_chunks": [4, 2], "total_chunks": 6},
    })

    assert "2 of 6 audio chunks" in mapped["transcription_warning_message"]
    assert "(chunks 2, 4)" in mapped["transcription_warning_message"]


def test_transcription_warning_message_falls_back_without_detail():
    warned = _map_row_to_transcription_dict({"id": "old", "progress_log": [], "has_transcription_warning": 1})
    clean = _map_row_to_transcription_dict({"id": "ok", "progress_log": []})

    assert warned["transcription_warning_message"] == "Transcript may be incomplete"
    assert clean["transcription_warning_message"] is None
