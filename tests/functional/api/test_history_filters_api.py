"""Server-side history filters and rows per page, against the test database."""

import uuid

from app.models import llm_operation as llm_operation_model
from app.models import transcription as transcription_model
from app.models import transcription_utils
from app.models import user_prompt as user_prompt_model
from app.models.transcription_utils.history_filters import HistoryFilters
from app.models.user import get_user_by_username
from app.services import history_filter_service


def _user(app):
    with app.app_context():
        return get_user_by_username("testuser_permissions")


def _create(app, user_id, *, api_used="whisper", language="en", minutes=1.2,
            days_old=0, pending_title=None, filename="audio.mp3"):
    job_id = str(uuid.uuid4())
    with app.app_context():
        transcription_model.create_transcription_job(
            job_id=job_id,
            user_id=user_id,
            filename=filename,
            api_used=api_used,
            file_size_mb=1.0,
            audio_length_minutes=minutes,
            context_prompt_used=False,
        )
        transcription_model.finalize_job_success(job_id, "Transcript text", language)
        cursor = transcription_model.get_cursor()
        cursor.execute(
            "UPDATE transcriptions SET created_at = NOW() - INTERVAL %s DAY,"
            " pending_workflow_prompt_title = %s WHERE id = %s",
            (days_old, pending_title, job_id),
        )
        transcription_model.get_db().commit()
    return job_id


def _run_workflow(app, user_id, job_id, prompt_id):
    with app.app_context():
        op_id = llm_operation_model.create_llm_operation(
            user_id=user_id, provider="GEMINI", operation_type="workflow",
            input_text="Prompt", transcription_id=job_id, prompt_id=prompt_id,
            status="processing", model="gemini-test",
        )
        llm_operation_model.update_llm_operation_status(op_id, "finished", result="Result")


def _ids(app, user_id, args, **kwargs):
    with app.app_context():
        filters = HistoryFilters.from_args(args)
        rows = transcription_utils.get_paginated_transcriptions(user_id, 1, 50, filters=filters, **kwargs)
        count = transcription_utils.count_visible_user_transcriptions(user_id, filters=filters, **kwargs)
    ids = {row["id"] for row in rows}
    assert count == len(ids)
    return ids


def test_each_filter_narrows_count_and_page(app, logged_in_client_with_permissions):
    user = _user(app)
    recent_short = _create(app, user.id, api_used="whisper", language="en", minutes=4.2)
    recent_long = _create(app, user.id, api_used="assemblyai", language="fr", minutes=75, days_old=3)
    old_mid = _create(app, user.id, api_used="whisper", language="fr", minutes=30, days_old=45)
    huge = _create(app, user.id, api_used="assemblyai", language="en", minutes=200, days_old=100)

    assert _ids(app, user.id, {}) == {recent_short, recent_long, old_mid, huge}
    assert _ids(app, user.id, {"date": "7d"}) == {recent_short, recent_long}
    assert _ids(app, user.id, {"date": "90d"}) == {recent_short, recent_long, old_mid}
    assert _ids(app, user.id, {"model": "assemblyai"}) == {recent_long, huge}
    assert _ids(app, user.id, {"lang": "fr"}) == {recent_long, old_mid}
    # Durations compare on whole minutes rounded up, as shown in the list (4.2 -> 5 min).
    assert _ids(app, user.id, {"dur_max": "5"}) == {recent_short}
    assert _ids(app, user.id, {"dur_min": "10", "dur_max": "60"}) == {old_mid}
    assert _ids(app, user.id, {"dur_min": "60"}) == {recent_long, huge}  # "Over 1 h" has no upper bound
    assert _ids(app, user.id, {"model": "whisper", "lang": "fr"}) == {old_mid}


def test_filters_combine_with_search(app, logged_in_client_with_permissions):
    user = _user(app)
    match = _create(app, user.id, language="fr", filename="standup-notes.mp3")
    _create(app, user.id, language="en", filename="standup-recap.mp3")
    _create(app, user.id, language="fr", filename="other.mp3")

    assert _ids(app, user.id, {"lang": "fr"}, search_query="standup") == {match}


def test_workflow_label_matches_pending_title_and_finished_workflows(app, logged_in_client_with_permissions):
    user = _user(app)
    with app.app_context():
        prompt = user_prompt_model.add_prompt(user.id, "Meeting summary", "Summarise", "#ffcc00")
    pending = _create(app, user.id, pending_title="Meeting summary")
    ran = _create(app, user.id)
    _run_workflow(app, user.id, ran, prompt.id)
    _create(app, user.id, pending_title="Action items")
    _create(app, user.id)

    with app.test_request_context():
        from flask_login import login_user
        login_user(user)
        filters = history_filter_service.resolve_filters({"workflow": "Meeting summary"}, user)
        assert filters.workflow_prompt_ids == [prompt.id]
        lookup = history_filter_service.build_prompt_lookup(user)
        options = history_filter_service.build_filter_options(user, lookup, language_names={"en": "English"})

    assert [o["value"] for o in options["workflows"]] == ["Action items", "Meeting summary"]
    assert [o["label"] for o in options["languages"]] == ["English"]
    assert [o["value"] for o in options["models"]] == ["whisper"]

    with app.app_context():
        rows = transcription_utils.get_paginated_transcriptions(user.id, 1, 50, filters=filters)
    assert {row["id"] for row in rows} == {pending, ran}


def test_index_renders_filters_count_and_keeps_filters_in_page_links(app, logged_in_client_with_permissions):
    client = logged_in_client_with_permissions
    user = _user(app)
    for i in range(12):
        _create(app, user.id, language="fr", filename=f"fr-{i}.mp3")
    _create(app, user.id, language="en", filename="en-only.mp3")

    plain = client.get("/").get_data(as_text=True)
    assert 'id="historyFiltersToggle"' in plain
    assert 'aria-expanded="false" aria-controls="historyFilters"' in plain
    assert 'role="group" aria-label="Filter transcription history" hidden' in plain
    assert "13 of 13" in plain

    page = client.get("/?lang=fr").get_data(as_text=True)
    assert "12 of 13" in page
    assert 'class="filter-toggle__count"' in page
    assert 'class="filter-chip is-active"' in page
    assert "en-only.mp3" not in page
    # Page links and chip menus keep the active filter.
    assert "/?lang=fr&amp;page=2#history" in page
    assert page.count("fr-") == 5  # default rows per page

    empty = client.get("/?lang=fr&model=assemblyai").get_data(as_text=True)
    assert "No transcriptions match these filters." in empty
    assert "0 of 13" in empty


def test_rows_per_page_is_remembered_in_the_session(app, logged_in_client_with_permissions):
    client = logged_in_client_with_permissions
    user = _user(app)
    for i in range(30):
        _create(app, user.id, filename=f"rowfile-{i:02d}.mp3")

    assert client.get("/").get_data(as_text=True).count("rowfile-") == 5
    first = client.get("/?per_page=25").get_data(as_text=True)
    assert first.count("rowfile-") == 25
    assert '<option value="25" selected>' in first
    # Remembered on the next visit without the parameter.
    assert client.get("/").get_data(as_text=True).count("rowfile-") == 25
    # Invalid values fall back to the remembered size.
    assert client.get("/?per_page=7").get_data(as_text=True).count("rowfile-") == 25


def test_search_endpoint_applies_filters(app, logged_in_client_with_permissions):
    client = logged_in_client_with_permissions
    user = _user(app)
    match = _create(app, user.id, api_used="assemblyai", filename="budget-review.mp3")
    _create(app, user.id, api_used="whisper", filename="budget-draft.mp3")

    response = client.get("/api/transcriptions/search?q=budget&model=assemblyai")
    assert response.status_code == 200
    payload = response.get_json()
    assert [item["id"] for item in payload["items"]] == [match]
    assert payload["filters"] == {"model": "assemblyai"}

    unfiltered = client.get("/api/transcriptions/search?q=budget").get_json()
    assert unfiltered["total"] == 2
