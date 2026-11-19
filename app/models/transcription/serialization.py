import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.logging_config import get_logger
from .warnings import describe_transcription_warning, parse_transcription_warning_detail


def _map_row_to_transcription_dict(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Maps a database row (dictionary) to a dictionary."""
    if not row:
        return None

    # Handle potential JSON decoding if progress_log is stored as TEXT
    if isinstance(row.get('progress_log'), str):
         try:
             row['progress_log'] = json.loads(row['progress_log'])
         except (json.JSONDecodeError, TypeError):
             get_logger(__name__).warning(f"Failed to decode progress_log JSON from TEXT field for job {row.get('id')}.")
             row['progress_log'] = ["Error decoding log."]  # Provide fallback

    # Ensure audio_length_minutes is float
    if 'audio_length_minutes' in row and row['audio_length_minutes'] is not None:
        try:
            row['audio_length_minutes'] = float(row['audio_length_minutes'])
        except (ValueError, TypeError):
            get_logger(__name__).warning(f"Could not convert audio_length_minutes '{row['audio_length_minutes']}' to float for job {row.get('id')}. Setting to 0.0.")
            row['audio_length_minutes'] = 0.0
    elif 'audio_length_minutes' not in row:
         row['audio_length_minutes'] = 0.0  # Default if column somehow missing after map

    # Ensure boolean fields are bool
    row['context_prompt_used'] = bool(row.get('context_prompt_used', False))
    row['has_transcription_warning'] = bool(row.get('has_transcription_warning', False))
    row['transcription_warning_detail'] = parse_transcription_warning_detail(
        row.get('transcription_warning_detail')
    )
    row['transcription_warning_message'] = describe_transcription_warning(
        row['has_transcription_warning'], row['transcription_warning_detail']
    )
    row['downloaded'] = bool(row.get('downloaded', False))
    row['is_hidden_from_user'] = bool(row.get('is_hidden_from_user', False))
    row['is_pinned'] = bool(row.get('is_pinned', False))

    # Convert datetime fields to string if they are datetime objects
    datetime_fields = ['hidden_date']
    for field in datetime_fields:
        if isinstance(row.get(field), datetime):
            try:
                row[field] = row[field].replace(tzinfo=timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
            except Exception as e:
                get_logger(__name__).warning(f"Error formatting datetime field '{field}' for job {row.get('id')}: {e}")
                row[field] = str(row[field])

    row['generated_title'] = row.get('generated_title')
    row['title_generation_status'] = row.get('title_generation_status', 'pending')

    # --- MODIFIED: Ensure pending_workflow_origin_prompt_id is present ---
    row['pending_workflow_prompt_text'] = row.get('pending_workflow_prompt_text')
    row['pending_workflow_prompt_title'] = row.get('pending_workflow_prompt_title')
    row['pending_workflow_prompt_color'] = row.get('pending_workflow_prompt_color')
    row['pending_workflow_origin_prompt_id'] = row.get('pending_workflow_origin_prompt_id') # Added
    # --- END MODIFIED ---
    row['public_api_invocation'] = bool(row.get('public_api_invocation', False))

    return row
