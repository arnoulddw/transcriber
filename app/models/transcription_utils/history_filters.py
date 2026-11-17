"""
Server-side filters for the user's transcription history.

The history list on the main page and the history search endpoint share these
helpers so that filters, search and pagination always agree on the same rows.
Filters arrive as query-string parameters:

* ``date``     preset key from ``DATE_PRESETS`` (rolling window ending now)
* ``model``    exact ``transcriptions.api_used`` value
* ``lang``     exact ``transcriptions.detected_language`` value
* ``dur_min``  minimum duration in minutes (multiple of ``DURATION_STEP``)
* ``dur_max``  maximum duration in minutes; ``DURATION_MAX`` or absent means "no upper bound"
* ``workflow`` workflow label (prompt title) shown on the history item
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from mysql.connector import Error as MySQLError

from app.database import get_cursor

# Rolling windows rather than calendar days: the database clock and the
# viewer's time zone can differ, and "last N days" is unambiguous either way.
DATE_PRESETS: Dict[str, int] = {
    '24h': 1,
    '7d': 7,
    '30d': 30,
    '90d': 90,
    '1y': 365,
}

DURATION_STEP = 5
DURATION_MAX = 180  # The slider's last stop reads "3 h+" (no upper bound).

PER_PAGE_OPTIONS: Tuple[int, ...] = (5, 10, 25, 50)
DEFAULT_PER_PAGE = 5

FILTER_PARAM_NAMES: Tuple[str, ...] = ('date', 'model', 'lang', 'dur_min', 'dur_max', 'workflow')


def _clean_text(value: Any, max_length: int = 255) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_length]


def _clean_duration(value: Any) -> Optional[int]:
    """Parse a duration bound, snapping to the slider's step and range."""
    if value is None or str(value).strip() == '':
        return None
    try:
        minutes = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    minutes = max(0, min(DURATION_MAX, minutes))
    return (minutes // DURATION_STEP) * DURATION_STEP


@dataclass
class HistoryFilters:
    """Validated history filters. Empty fields mean "any"."""

    date: Optional[str] = None
    model: Optional[str] = None
    language: Optional[str] = None
    duration_min: Optional[int] = None
    duration_max: Optional[int] = None
    workflow: Optional[str] = None
    # Prompt ids whose title equals ``workflow`` (resolved by the caller, who
    # knows which user and template prompts the history labels come from).
    workflow_prompt_ids: List[int] = field(default_factory=list)

    @classmethod
    def from_args(cls, args: Mapping[str, Any]) -> 'HistoryFilters':
        date = _clean_text(args.get('date'), 8)
        if date not in DATE_PRESETS:
            date = None

        duration_min = _clean_duration(args.get('dur_min'))
        duration_max = _clean_duration(args.get('dur_max'))
        if duration_min == 0:
            duration_min = None
        if duration_max is not None and duration_max >= DURATION_MAX:
            duration_max = None
        if duration_min is not None and duration_max is not None and duration_min > duration_max:
            duration_min, duration_max = duration_max, duration_min

        return cls(
            date=date,
            model=_clean_text(args.get('model'), 50),
            language=_clean_text(args.get('lang'), 10),
            duration_min=duration_min,
            duration_max=duration_max,
            workflow=_clean_text(args.get('workflow'), 100),
        )

    @property
    def has_duration(self) -> bool:
        return self.duration_min is not None or self.duration_max is not None

    @property
    def active_count(self) -> int:
        """Number of active chips (duration counts once even with two bounds)."""
        return sum(
            1 for active in (
                self.date, self.model, self.language, self.has_duration, self.workflow,
            ) if active
        )

    @property
    def is_active(self) -> bool:
        return self.active_count > 0

    def to_query(self) -> Dict[str, Any]:
        """Query-string parameters that reproduce these filters."""
        query: Dict[str, Any] = {}
        if self.date:
            query['date'] = self.date
        if self.model:
            query['model'] = self.model
        if self.language:
            query['lang'] = self.language
        if self.duration_min is not None:
            query['dur_min'] = self.duration_min
        if self.duration_max is not None:
            query['dur_max'] = self.duration_max
        if self.workflow:
            query['workflow'] = self.workflow
        return query


def build_history_filter_clause(
    filters: Optional[HistoryFilters],
    user_id: int,
    alias: str = 't',
) -> Tuple[str, List[Any]]:
    """Return an ``AND ...`` SQL fragment and its parameters for ``filters``."""
    if not filters or not filters.is_active:
        return '', []

    clauses: List[str] = []
    params: List[Any] = []

    if filters.date:
        clauses.append(f"{alias}.created_at >= (NOW() - INTERVAL %s DAY)")
        params.append(DATE_PRESETS[filters.date])
    if filters.model:
        clauses.append(f"{alias}.api_used = %s")
        params.append(filters.model)
    if filters.language:
        clauses.append(f"{alias}.detected_language = %s")
        params.append(filters.language)
    # History rows show whole minutes rounded up, so compare on the same value.
    if filters.duration_min is not None:
        clauses.append(f"CEIL({alias}.audio_length_minutes) >= %s")
        params.append(filters.duration_min)
    if filters.duration_max is not None:
        clauses.append(f"CEIL({alias}.audio_length_minutes) <= %s")
        params.append(filters.duration_max)
    if filters.workflow:
        workflow_sql = f"{alias}.pending_workflow_prompt_title = %s"
        params.append(filters.workflow)
        prompt_ids = sorted({int(pid) for pid in filters.workflow_prompt_ids})
        if prompt_ids:
            placeholders = ', '.join(['%s'] * len(prompt_ids))
            workflow_sql += (
                " OR EXISTS (SELECT 1 FROM llm_operations wf"
                f" WHERE wf.transcription_id = {alias}.id AND wf.user_id = %s"
                " AND wf.operation_type = 'workflow' AND wf.status IN ('finished', 'error')"
                f" AND wf.prompt_id IN ({placeholders}))"
            )
            params.append(user_id)
            params.extend(prompt_ids)
        clauses.append(f"({workflow_sql})")

    return ''.join(f" AND {clause}" for clause in clauses), params


def get_history_filter_values(user_id: int) -> Dict[str, List[Any]]:
    """
    Distinct values present in the user's visible history, used to build the
    Model, Language and Workflow dropdowns. Workflow values are returned raw:
    ``workflow_prompt_ids`` (to be mapped to titles by the caller) and
    ``pending_workflow_titles``.
    """
    log_prefix = f"[DB:History:FilterValues:User:{user_id}]"
    base_where = "t.user_id = %s AND t.is_hidden_from_user = FALSE AND t.status = 'finished'"
    values: Dict[str, List[Any]] = {
        'models': [],
        'languages': [],
        'workflow_prompt_ids': [],
        'pending_workflow_titles': [],
    }
    cursor = get_cursor()
    try:
        cursor.execute(
            f"SELECT DISTINCT t.api_used AS value FROM transcriptions t WHERE {base_where}"
            " AND t.api_used IS NOT NULL AND t.api_used <> '' ORDER BY value",
            (user_id,),
        )
        values['models'] = [row['value'] for row in cursor.fetchall()]

        cursor.execute(
            f"SELECT DISTINCT t.detected_language AS value FROM transcriptions t WHERE {base_where}"
            " AND t.detected_language IS NOT NULL AND t.detected_language <> ''"
            " AND LOWER(t.detected_language) NOT IN ('unknown', 'und') ORDER BY value",
            (user_id,),
        )
        values['languages'] = [row['value'] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT DISTINCT lo.prompt_id AS value FROM llm_operations lo"
            " JOIN transcriptions t ON t.id = lo.transcription_id"
            f" WHERE {base_where} AND lo.user_id = %s AND lo.operation_type = 'workflow'"
            " AND lo.status IN ('finished', 'error') AND lo.prompt_id IS NOT NULL",
            (user_id, user_id),
        )
        values['workflow_prompt_ids'] = [row['value'] for row in cursor.fetchall()]

        cursor.execute(
            f"SELECT DISTINCT t.pending_workflow_prompt_title AS value FROM transcriptions t WHERE {base_where}"
            " AND t.pending_workflow_prompt_title IS NOT NULL AND t.pending_workflow_prompt_title <> ''",
            (user_id,),
        )
        values['pending_workflow_titles'] = [row['value'] for row in cursor.fetchall()]
    except MySQLError as err:
        logging.error("%s Error loading history filter values: %s", log_prefix, err, exc_info=True)
    return values


def resolve_workflow_labels(
    prompt_lookup: Mapping[Any, Mapping[str, Any]],
    prompt_ids: Iterable[Any],
) -> Dict[str, List[int]]:
    """
    Map workflow label titles to the prompt ids that display under that title.

    ``prompt_lookup`` has the shape built by the main page: user prompt ids as
    plain keys, template prompts as ``"template_<id>"``. A raw ``prompt_id`` is
    shown with the user prompt's title first and the template's title second,
    so the same precedence is applied here.
    """
    titles: Dict[str, List[int]] = {}
    for raw_id in prompt_ids:
        if raw_id is None:
            continue
        try:
            prompt_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        prompt = prompt_lookup.get(prompt_id) or prompt_lookup.get(f"template_{prompt_id}")
        title = (prompt or {}).get('title')
        if title:
            titles.setdefault(title, []).append(prompt_id)
    return titles


def resolve_per_page(requested: Any, remembered: Any = None) -> Tuple[int, bool]:
    """
    Pick the page size: a valid ``requested`` value wins, then a valid
    ``remembered`` one, then the default. Returns ``(per_page, from_request)``.
    """
    for candidate, from_request in ((requested, True), (remembered, False)):
        try:
            value = int(candidate)
        except (TypeError, ValueError):
            continue
        if value in PER_PAGE_OPTIONS:
            return value, from_request
    return DEFAULT_PER_PAGE, False


__all__ = [
    'DATE_PRESETS',
    'DEFAULT_PER_PAGE',
    'DURATION_MAX',
    'DURATION_STEP',
    'FILTER_PARAM_NAMES',
    'HistoryFilters',
    'PER_PAGE_OPTIONS',
    'build_history_filter_clause',
    'get_history_filter_values',
    'resolve_per_page',
    'resolve_workflow_labels',
]
