# tests/functional/test_transcription_management.py
# Contains functional tests for transcription management features.

import io
from unittest.mock import patch, MagicMock

from flask import url_for

from app.models import transcription as transcription_model
from app.services.api_clients.exceptions import TranscriptionApiError

# Constants for tests
SUCCESS_TEST_FILENAME = "test_audio.mp3"
INVALID_TEST_FILENAME = "test_document.txt"


class TestTranscriptionManagement:
    """
    Test suite for transcription management functionalities such as
    file uploads and history pagination.
    """
    @patch("app.api.transcriptions.submit_transcription_job")
    def test_successful_upload_and_transcription(self, mock_submit_transcription_job, logged_in_client):
        """
        Test case for a successful file upload and transcription initiation.
        """
        mock_submit_transcription_job.return_value = None

        # Prepare the data for the POST request
        data = {
            "api_choice": "gpt-4o-transcribe",
            "language_code": "en",
            "audio_file": (io.BytesIO(b"test audio data"), SUCCESS_TEST_FILENAME),
        }

        # Make the request to the transcribe endpoint
        response = logged_in_client.post(
            url_for("transcriptions.transcribe_audio"),
            data=data,
            content_type="multipart/form-data",
        )

        # Assert that the request was successful
        assert response.status_code == 202
        response_data = response.get_json()
        assert response_data["message"] == "Transcription job started successfully."
        assert "job_id" in response_data

        # Assert that the background process was queued
        mock_submit_transcription_job.assert_called_once()

    def test_upload_with_invalid_file_type(self, logged_in_client):
        """
        Test case for file upload failure due to an invalid file type.
        """
        # Prepare the data for the POST request
        data = {
            "api_choice": "gpt-4o-transcribe",
            "language_code": "en",
            "audio_file": (io.BytesIO(b"test data"), INVALID_TEST_FILENAME),
        }

        # Make the request to the transcribe endpoint
        response = logged_in_client.post(
            url_for("transcriptions.transcribe_audio"),
            data=data,
            content_type="multipart/form-data",
        )

        # Assert that the request was a bad request
        assert response.status_code == 400
        response_data = response.get_json()
        assert response_data["error"] == "This file type is not supported for transcription."

    @patch("app.models.transcription_utils.count_visible_user_transcriptions")
    @patch("app.models.transcription_utils.get_paginated_transcriptions")
    def test_history_pagination(self, mock_get_paginated_transcriptions, mock_count_transcriptions, logged_in_client):
        """
        Test case for successful pagination of the transcription history.
        """
        # Mock the functions to simulate a user with more than one page of transcriptions
        # (the default page size is 10 rows, the smallest "Rows per page" option)
        mock_count_transcriptions.return_value = 30
        mock_get_paginated_transcriptions.return_value = [
            {"id": i, "filename": f"test_{i}.mp3", "status": "finished", "audio_length_minutes": 1} for i in range(5)
        ]

        # Make a request to the main page
        response = logged_in_client.get(url_for("main.index"))

        # Assert that the request was successful
        assert response.status_code == 200
        assert b"Previous" in response.data
        assert b"Next" in response.data

    @patch("app.models.transcription_utils.count_visible_user_transcriptions")
    @patch("app.models.transcription_utils.get_paginated_transcriptions")
    def test_pagination_items_per_page(self, mock_get_paginated_transcriptions, mock_count_transcriptions, logged_in_client):
        """
        Test case to verify that the number of items per page is correct.
        """
        # Mock the functions to simulate a user with 7 transcriptions
        mock_count_transcriptions.return_value = 7
        mock_get_paginated_transcriptions.return_value = [
            {"id": i, "filename": f"test_{i}.mp3", "status": "finished", "audio_length_minutes": 1} for i in range(5)
        ]

        # Make a request to the first page
        response = logged_in_client.get(url_for("main.index", page=1))

        # Assert that the request was successful and the correct number of items are displayed
        assert response.status_code == 200
        assert response.data.count(b"test_") == 5

        # Mock the return value for the second page
        mock_get_paginated_transcriptions.return_value = [
            {"id": i, "filename": f"test_{i}.mp3", "status": "finished", "audio_length_minutes": 1} for i in range(5, 7)
        ]

        # Make a request to the second page
        response = logged_in_client.get(url_for("main.index", page=2))

        # Assert that the request was successful and the correct number of items are displayed
        assert response.status_code == 200
        assert response.data.count(b"test_") == 2

    @patch("app.api.transcriptions.submit_transcription_job")
    def test_successful_gpt4o_upload(self, mock_submit_transcription_job, logged_in_client):
        """
        Test case for a successful file upload using GPT-4o Transcribe.
        """
        mock_submit_transcription_job.return_value = None

        data = {
            "api_choice": "gpt-4o-transcribe",
            "language_code": "en",
            "audio_file": (io.BytesIO(b"test audio data"), SUCCESS_TEST_FILENAME),
        }

        response = logged_in_client.post(
            url_for("transcriptions.transcribe_audio"),
            data=data,
            content_type="multipart/form-data",
        )

        assert response.status_code == 202
        response_data = response.get_json()
        assert response_data["message"] == "Transcription job started successfully."
        assert "job_id" in response_data

        mock_submit_transcription_job.assert_called_once()

    @patch("app.api.transcriptions.submit_transcription_job")
    def test_successful_gpt_transcribe_upload(
        self, mock_submit_transcription_job, logged_in_client_with_permissions
    ):
        """GPT Transcribe is accepted as an active OpenAI transcription model."""
        data = {
            "api_choice": "gpt-transcribe",
            "language_code": "auto",
            "audio_file": (
                io.BytesIO(b"test audio data"),
                SUCCESS_TEST_FILENAME,
            ),
        }

        response = logged_in_client_with_permissions.post(
            url_for("transcriptions.transcribe_audio"),
            data=data,
            content_type="multipart/form-data",
        )

        assert response.status_code == 202
        mock_submit_transcription_job.assert_called_once()

    def test_diarization_permission_failure_cleans_uploaded_file(
        self, app, logged_in_client_with_permissions, tmp_path, monkeypatch
    ):
        """A rejected post-upload permission check must not leak the temp file."""
        app.config["TEMP_UPLOADS_DIR"] = str(tmp_path)

        def allow_everything_except_diarization(_user, permission):
            return permission != "allow_speaker_diarization"

        monkeypatch.setattr(
            "app.api.transcriptions.check_permission",
            allow_everything_except_diarization,
        )
        monkeypatch.setattr(
            "app.api.transcriptions.file_service.get_audio_duration",
            lambda _path: (60.0, 1.0),
        )

        response = logged_in_client_with_permissions.post(
            url_for("transcriptions.transcribe_audio"),
            data={
                "api_choice": "universal",
                "language_code": "en",
                "speaker_diarization": "true",
                "audio_file": (io.BytesIO(b"test audio data"), SUCCESS_TEST_FILENAME),
            },
            content_type="multipart/form-data",
        )

        assert response.status_code == 403
        assert list(tmp_path.iterdir()) == []

    def test_openrouter_upload_forwards_model_to_job_and_queue(
        self, app, logged_in_client_with_permissions, tmp_path
    ):
        """An authenticated OpenRouter upload persists and queues its model slug."""
        model_slug = "openai/gpt-transcribe"
        app.config["TEMP_UPLOADS_DIR"] = str(tmp_path)

        with patch(
            "app.api.transcriptions.transcription_catalog_model.get_active_models",
            return_value=[
                {
                    "code": model_slug,
                    "model_key": f"openrouter:{model_slug}",
                    "model_slug": model_slug,
                    "provider_code": "openrouter",
                    "display_name": "OpenAI GPT Transcribe",
                    "permission_key": "use_api_openrouter",
                    "required_api_key": "openrouter",
                    "is_default": False,
                }
            ],
        ), patch(
            "app.api.transcriptions.transcription_catalog_model.get_active_languages",
            return_value=[{"code": "en", "display_name": "English", "is_default": True}],
        ), patch(
            "app.api.transcriptions.file_service.get_audio_duration",
            return_value=(60.0, 1.0),
        ), patch(
            "app.api.transcriptions.pricing_service.get_price",
            return_value=None,
        ) as mock_pricing, patch(
            "app.api.transcriptions.role_model.reserve_usage_if_allowed",
            return_value=(True, ""),
        ), patch(
            "app.api.transcriptions.transcription_model.create_transcription_job"
        ) as mock_create_job, patch(
            "app.api.transcriptions.submit_transcription_job"
        ) as mock_submit_transcription_job:
            response = logged_in_client_with_permissions.post(
                url_for("transcriptions.transcribe_audio"),
                data={
                    "api_choice": f"openrouter:{model_slug}",
                    "openrouter_model": model_slug,
                    "language_code": "en",
                    "audio_file": (io.BytesIO(b"test audio data"), SUCCESS_TEST_FILENAME),
                },
                content_type="multipart/form-data",
            )

        assert response.status_code == 202
        mock_pricing.assert_called_once_with(item_type='transcription', item_key=model_slug)
        mock_create_job.assert_called_once()
        assert mock_create_job.call_args.kwargs["api_used"] == f"openrouter:{model_slug}"
        assert mock_create_job.call_args.kwargs["api_model"] == model_slug

        mock_submit_transcription_job.assert_called_once()
        queued_args = mock_submit_transcription_job.call_args.args
        assert queued_args[7] == f"openrouter:{model_slug}"
        assert queued_args[-1] == model_slug
