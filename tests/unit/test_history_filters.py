"""Parsing and SQL building for the Transcription History filters."""

from app.models.transcription_utils.history_filters import (
    DEFAULT_PER_PAGE,
    HistoryFilters,
    build_history_filter_clause,
    resolve_per_page,
    resolve_workflow_labels,
)


def test_no_args_means_no_filters():
    filters = HistoryFilters.from_args({})
    assert not filters.is_active
    assert filters.active_count == 0
    assert build_history_filter_clause(filters, user_id=1) == ('', [])
    assert filters.to_query() == {}


def test_unknown_date_preset_and_blank_values_are_ignored():
    filters = HistoryFilters.from_args({'date': 'forever', 'model': '  ', 'lang': '', 'workflow': ' '})
    assert not filters.is_active


def test_duration_snaps_to_step_and_full_range_means_any():
    filters = HistoryFilters.from_args({'dur_min': '12', 'dur_max': '999'})
    assert filters.duration_min == 10
    assert filters.duration_max is None  # "3 h+" is no upper bound
    assert HistoryFilters.from_args({'dur_min': '0', 'dur_max': '180'}).has_duration is False
    assert HistoryFilters.from_args({'dur_min': 'abc'}).has_duration is False


def test_swapped_duration_bounds_are_reordered():
    filters = HistoryFilters.from_args({'dur_min': '60', 'dur_max': '10'})
    assert (filters.duration_min, filters.duration_max) == (10, 60)


def test_duration_counts_as_one_active_filter():
    filters = HistoryFilters.from_args({'date': '30d', 'dur_min': '10', 'dur_max': '60'})
    assert filters.active_count == 2
    assert filters.to_query() == {'date': '30d', 'dur_min': 10, 'dur_max': 60}


def test_clause_covers_every_filter_with_bound_parameters():
    filters = HistoryFilters.from_args({
        'date': '7d', 'model': 'whisper', 'lang': 'fr',
        'dur_min': '10', 'dur_max': '60', 'workflow': "Meeting'; DROP",
    })
    filters.workflow_prompt_ids = [4, 2]
    sql, params = build_history_filter_clause(filters, user_id=9)

    assert "t.created_at >= (NOW() - INTERVAL %s DAY)" in sql
    assert "t.api_used = %s" in sql
    assert "t.detected_language = %s" in sql
    assert "CEIL(t.audio_length_minutes) >= %s" in sql
    assert "CEIL(t.audio_length_minutes) <= %s" in sql
    assert "wf.prompt_id IN (%s, %s)" in sql
    assert "DROP" not in sql  # user input only travels as parameters
    assert params == [7, 'whisper', 'fr', 10, 60, "Meeting'; DROP", 9, 2, 4]


def test_workflow_without_known_prompts_matches_pending_label_only():
    filters = HistoryFilters.from_args({'workflow': 'Summary'})
    sql, params = build_history_filter_clause(filters, user_id=1)
    assert sql == " AND (t.pending_workflow_prompt_title = %s)"
    assert params == ['Summary']


def test_workflow_labels_prefer_user_prompt_over_template_with_same_id():
    lookup = {
        3: {'title': 'My summary'},
        'template_3': {'title': 'Template summary'},
        'template_5': {'title': 'Action items'},
        7: {'title': 'Action items'},
    }
    labels = resolve_workflow_labels(lookup, [3, 5, 7, None, 'x'])
    assert labels == {'My summary': [3], 'Action items': [5, 7]}


def test_per_page_request_wins_then_remembered_then_default():
    assert resolve_per_page('25', 50) == (25, True)
    assert resolve_per_page(None, 50) == (50, False)
    assert resolve_per_page('7', '13') == (DEFAULT_PER_PAGE, False)
    assert resolve_per_page('abc', None) == (DEFAULT_PER_PAGE, False)
