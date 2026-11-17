"""
Composable transcription utilities grouped by domain.

This package re-exports the original helpers so existing imports such as
`from app.models import transcription_utils` continue to work without changes.
"""

from .filtering import VALID_TRANSCRIPTION_COLUMNS_FOR_FILTERING
from .history import (
    count_visible_user_transcriptions,
    get_all_transcriptions_for_admin,
    get_paginated_transcriptions,
    physically_delete_hidden_records,
    purge_user_history,
)
from .history_filters import (
    HistoryFilters,
    get_history_filter_values,
)
from .user_stats import (
    count_user_errors,
    count_user_transcriptions,
    get_total_audio_length_in_minutes,
)
from .admin_analytics import (
    count_errors_since,
    count_jobs_in_range,
    count_successful_title_generations_in_range,
    count_transcriptions_since,
    count_workflow_jobs_with_filters,
    get_api_distribution_in_range,
    get_api_error_rate_distribution_in_range,
    get_common_error_messages_in_range,
    get_common_workflow_error_messages,
    get_cost_analytics_by_component,
    get_cost_analytics_by_role,
    get_language_distribution_in_range,
    get_workflow_model_distribution,
    sum_minutes_in_range,
)

__all__ = [
    "VALID_TRANSCRIPTION_COLUMNS_FOR_FILTERING",
    "get_all_transcriptions_for_admin",
    "count_user_transcriptions",
    "count_user_errors",
    "get_total_audio_length_in_minutes",
    "purge_user_history",
    "physically_delete_hidden_records",
    "count_transcriptions_since",
    "count_errors_since",
    "count_jobs_in_range",
    "sum_minutes_in_range",
    "get_api_distribution_in_range",
    "get_api_error_rate_distribution_in_range",
    "get_language_distribution_in_range",
    "get_common_error_messages_in_range",
    "get_workflow_model_distribution",
    "get_common_workflow_error_messages",
    "count_visible_user_transcriptions",
    "get_paginated_transcriptions",
    "HistoryFilters",
    "get_history_filter_values",
    "count_successful_title_generations_in_range",
    "count_workflow_jobs_with_filters",
    "get_cost_analytics_by_component",
    "get_cost_analytics_by_role",
]
