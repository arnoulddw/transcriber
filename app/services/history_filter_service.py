"""
Builds what the Transcription History needs for its filters: the validated
filters for a request, the dropdown options, and the page size.

Rows per page is remembered per user in the Flask session (signed cookie):
picking 10/25/50 sticks while the user stays signed in on that browser and
falls back to the default on a new sign-in or another device. It is a view
preference, so it is deliberately not stored on the user record.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Tuple

from app.models.transcription_utils.history_filters import (
    DATE_PRESETS,
    HistoryFilters,
    get_history_filter_values,
    resolve_per_page,
    resolve_workflow_labels,
)
from app.services import admin_management_service, user_service

PER_PAGE_SESSION_KEY = 'history_per_page'


def build_prompt_lookup(user) -> Dict[Any, Dict[str, Any]]:
    """
    Workflow labels as shown in history: user prompt ids as plain keys and
    template prompts as ``"template_<id>"``. Empty without workflow permission.
    """
    lookup: Dict[Any, Dict[str, Any]] = {}
    if not user.has_permission('allow_workflows'):
        return lookup
    try:
        for prompt in user_service.get_user_prompts(user.id):
            lookup[prompt.id] = {'title': prompt.title, 'color': prompt.color}
        # All templates regardless of language: a workflow may have run with a
        # template in another language than the user's current default.
        for template in admin_management_service.get_template_prompts(language=None):
            lookup[f"template_{template.id}"] = {'title': template.title, 'color': template.color}
    except Exception as err:  # Prompts are decoration; history must still load.
        logging.error("[SERVICE:HistoryFilters] Error loading prompts for labels: %s", err, exc_info=True)
    return lookup


def resolve_filters(
    args: Mapping[str, Any],
    user,
    prompt_lookup: Optional[Mapping[Any, Mapping[str, Any]]] = None,
) -> HistoryFilters:
    """Parse filters from request args and resolve the workflow label to prompt ids."""
    filters = HistoryFilters.from_args(args)
    if filters.workflow:
        if not user.has_permission('allow_workflows'):
            filters.workflow = None
        else:
            lookup = prompt_lookup if prompt_lookup is not None else build_prompt_lookup(user)
            candidate_ids = [key for key in lookup if isinstance(key, int)]
            candidate_ids += [
                int(key.split('_', 1)[1]) for key in lookup
                if isinstance(key, str) and key.startswith('template_')
            ]
            labels = resolve_workflow_labels(lookup, candidate_ids)
            filters.workflow_prompt_ids = labels.get(filters.workflow, [])
    return filters


def build_filter_options(
    user,
    prompt_lookup: Mapping[Any, Mapping[str, Any]],
    language_names: Mapping[str, str],
    model_names: Optional[Mapping[str, str]] = None,
) -> Dict[str, List[Dict[str, str]]]:
    """Dropdown options, limited to values that occur in the user's history.
    Model labels default to the raw ``api_used`` value; the template maps them
    to display names with ``API_NAME_MAP_FRONTEND``."""
    model_names = model_names or {}
    values = get_history_filter_values(user.id)

    models = [
        {'value': code, 'label': model_names.get(code, code)}
        for code in values['models']
    ]
    models.sort(key=lambda item: item['label'].lower())

    languages = [
        {'value': code, 'label': language_names.get(code, code.capitalize())}
        for code in values['languages']
    ]
    languages.sort(key=lambda item: item['label'].lower())

    workflow_titles = set(values['pending_workflow_titles'])
    if user.has_permission('allow_workflows'):
        workflow_titles.update(resolve_workflow_labels(prompt_lookup, values['workflow_prompt_ids']))
    else:
        workflow_titles = set()
    workflows = [{'value': title, 'label': title} for title in sorted(workflow_titles, key=str.lower)]

    return {'models': models, 'languages': languages, 'workflows': workflows}


def date_preset_options(gettext) -> List[Dict[str, str]]:
    labels = {
        '24h': gettext('Last 24 hours'),
        '7d': gettext('Last 7 days'),
        '30d': gettext('Last 30 days'),
        '90d': gettext('Last 90 days'),
        '1y': gettext('Last 12 months'),
    }
    return [{'value': key, 'label': labels[key]} for key in DATE_PRESETS]


def date_filter_label(filters: HistoryFilters, presets: List[Dict[str, str]], gettext, format_day) -> str:
    """Chip text for the active date filter (preset label or custom range), or ''.

    ``format_day`` turns a ``date`` into display text; the year is left out when
    both ends fall in the current year so the chip stays short.
    """
    if filters.has_date_range:
        lo, hi = filters.date_from, filters.date_to
        this_year = date.today().year
        with_year = any(d and d.year != this_year for d in (lo, hi))
        fmt = 'medium' if with_year else 'd MMM'
        if lo and hi:
            if lo == hi:
                return format_day(lo, fmt)
            return f"{format_day(lo, fmt)} – {format_day(hi, fmt)}"
        if lo:
            return gettext('Since %(day)s', day=format_day(lo, fmt))
        return gettext('Until %(day)s', day=format_day(hi, fmt))
    if filters.date:
        return next((p['label'] for p in presets if p['value'] == filters.date), '')
    return ''


def resolve_session_per_page(args: Mapping[str, Any], session: MutableMapping[str, Any]) -> Tuple[int, bool]:
    """Page size from ``?per_page=`` (remembered in the session) or the session."""
    per_page, from_request = resolve_per_page(args.get('per_page'), session.get(PER_PAGE_SESSION_KEY))
    if from_request:
        session[PER_PAGE_SESSION_KEY] = per_page
    return per_page, from_request
