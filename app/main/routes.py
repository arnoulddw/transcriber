# app/main/routes.py
# Defines the routes for the main application pages (e.g., the homepage).

import logging
import math
from flask import render_template, current_app, g, abort, request, redirect, session, url_for
from flask_login import current_user, login_required
from flask_babel import gettext as _

# Import the main blueprint defined in app/main/__init__.py
from . import main_bp
from app.models import transcription_utils
from app.models import transcription_catalog as transcription_catalog_model
# --- ADDED: Import llm_operation model ---
from app.models import llm_operation as llm_operation_model
# --- END ADDED ---
# Import services for prompt matching
from app.services import user_service, admin_management_service
from app.core.decorators import check_permission
from app.services import history_filter_service
from app.models.transcription_utils.history_filters import DURATION_MAX, DURATION_STEP, PER_PAGE_OPTIONS

@main_bp.route('/')
@login_required
def index():
    """
    Renders the main index page (index.html).
    Passes necessary configuration and context to the template.
    Determines effective defaults based on user preferences or system config.
    Handles pagination for transcription history.
    Augments transcription data with the latest finished/errored LLM operation info.
    Adds a flag indicating if title polling should occur for each transcription.
    """
    log_prefix = "[ROUTE:Main:Index]"
    user_info = f"User:{current_user.id}" if current_user.is_authenticated else "Anonymous"
    logging.debug(f"{log_prefix} Accessing route '/'. ({user_info})")

    # --- Determine Effective Defaults ---
    catalog_models = transcription_catalog_model.get_active_models()
    logging.debug(f"{log_prefix} Loaded {len(catalog_models)} active transcription models from catalog.")
    active_model_keys = {
        str(model.get('model_key') or model.get('code') or '').strip()
        for model in catalog_models
        if model.get('code')
    }
    active_model_codes = {
        str(model.get('code') or '').strip()
        for model in catalog_models
        if model.get('code')
    }

    supported_languages = transcription_catalog_model.get_language_map()
    effective_default_language = (
        transcription_catalog_model.get_default_language_code()
        or current_app.config.get('DEFAULT_LANGUAGE')
        or 'auto'
    )
    effective_default_api = (
        transcription_catalog_model.get_default_model_code()
        or current_app.config.get('DEFAULT_TRANSCRIPTION_PROVIDER')
    )
    if current_user.is_authenticated:
        if current_user.default_content_language:
            if current_user.default_content_language in supported_languages:
                effective_default_language = current_user.default_content_language
                logging.debug(f"{log_prefix} Using user's default language: {effective_default_language}")
            else:
                logging.warning(
                    f"{log_prefix} User's preferred language '{current_user.default_content_language}' "
                    f"is not currently available. Using catalog default: {effective_default_language}"
                )
        else:
            logging.debug(f"{log_prefix} User has no language preference, using system default: {effective_default_language}")

        if current_user.default_transcription_model:
            stored_model = transcription_catalog_model.get_model_by_code(
                current_user.default_transcription_model
            )
            stored_model_key = (stored_model or {}).get('model_key')
            if stored_model_key in active_model_keys:
                effective_default_api = stored_model_key
                logging.debug(f"{log_prefix} Using user's default model: {effective_default_api}")
            elif current_user.default_transcription_model in active_model_codes:
                # Compatibility for a legacy bare value while the database is
                # being migrated to provider-qualified defaults.
                effective_default_api = current_user.default_transcription_model
                logging.debug(f"{log_prefix} Using legacy user's default model: {effective_default_api}")
            else:
                logging.warning(
                    f"{log_prefix} User's preferred model '{current_user.default_transcription_model}' "
                    f"is not currently allowed. Falling back to catalog default: {effective_default_api}"
                )
        else:
            logging.debug(f"{log_prefix} User has no model preference, using system default: {effective_default_api}")

    else:
        logging.debug(f"{log_prefix} Using system defaults (Lang: {effective_default_language}, API: {effective_default_api})")
    # --- End Determine Effective Defaults ---

    # --- Pagination, filters and rows per page ---
    page = request.args.get('page', 1, type=int)
    per_page, _from_request = history_filter_service.resolve_session_per_page(request.args, session)
    pagination = None
    transcriptions = []
    all_prompts_lookup = history_filter_service.build_prompt_lookup(current_user)
    history_filters = history_filter_service.resolve_filters(request.args, current_user, all_prompts_lookup)
    filtered_total = 0
    unfiltered_total = 0
    filter_options = {'models': [], 'languages': [], 'workflows': []}

    try:
        # Fetch paginated transcriptions (now includes llm_operation_id)
        total_items = transcription_utils.count_visible_user_transcriptions(
            current_user.id, filters=history_filters
        )
        filtered_total = total_items
        unfiltered_total = (
            transcription_utils.count_visible_user_transcriptions(current_user.id)
            if history_filters.is_active else total_items
        )
        if unfiltered_total > 0:
            filter_options = history_filter_service.build_filter_options(
                current_user,
                all_prompts_lookup,
                language_names=supported_languages,
            )
        if total_items > 0:
            total_pages = math.ceil(total_items / per_page)
            page = max(1, min(page, total_pages))
            transcriptions = transcription_utils.get_paginated_transcriptions(
                current_user.id, page, per_page, filters=history_filters
            )

            user_can_poll_title = current_user.enable_auto_title_generation and current_user.has_permission('allow_auto_title_generation')
            for t in transcriptions:
                title_status = t.get('title_generation_status', 'pending')
                t['should_poll_title'] = user_can_poll_title and title_status in ['pending', 'processing']

                llm_op_id = t.get('llm_operation_id')
                if llm_op_id:
                    llm_op = llm_operation_model.get_llm_operation_by_id(llm_op_id, current_user.id)
                    if llm_op:
                        t['llm_operation_status'] = llm_op.get('status')
                        t['llm_operation_result'] = llm_op.get('result')
                        t['llm_operation_error'] = llm_op.get('error')
                        t['llm_operation_ran_at'] = llm_op.get('completed_at')
                        t['llm_operation_prompt'] = llm_op.get('input_text')
                        t['llm_operation_prompt_id'] = llm_op.get('prompt_id') # This is the raw ID
                        t['llm_operation_provider'] = llm_op.get('provider')

                        prompt_key_to_lookup = t['llm_operation_prompt_id']
                        matched_prompt = None
                        if prompt_key_to_lookup is not None:
                            # Try matching as a user prompt ID (integer)
                            matched_prompt = all_prompts_lookup.get(prompt_key_to_lookup)
                            if not matched_prompt:
                                # Try matching as a template prompt ID (string "template_ID")
                                matched_prompt = all_prompts_lookup.get(f"template_{prompt_key_to_lookup}")
                        
                        if matched_prompt:
                            t['matched_workflow_title'] = matched_prompt['title']
                            t['matched_workflow_color'] = matched_prompt['color']
                        else:
                            t['matched_workflow_title'] = None
                            t['matched_workflow_color'] = None
                    else:
                        logging.warning(f"{log_prefix} Could not fetch details for LLM operation ID {llm_op_id} linked to transcription {t['id']}.")
                        t['llm_operation_status'] = 'error'
                        t['llm_operation_error'] = 'Could not load workflow details.'
                else: # No llm_operation_id on the transcription record
                    # This handles cases where a workflow was pre-applied but hasn't fully processed
                    # to link the llm_operation_id back to the transcription record yet,
                    # or if the transcription failed before the workflow could run.
                    # We use the 'pending_workflow_...' fields from the transcription table.
                    t['llm_operation_status'] = t.get('llm_operation_status', 'idle') # Use existing status if available, else idle
                    if t.get('pending_workflow_prompt_text') and t['llm_operation_status'] == 'idle':
                        # If there was a pending workflow and status is still idle, it implies it hasn't started or linked yet.
                        # We can infer 'pending' or 'processing' if we had more info, but for display, use pending details.
                        t['llm_operation_status'] = 'pending' # Or 'processing' if more appropriate
                    
                    t['llm_operation_prompt'] = t.get('pending_workflow_prompt_text')
                    t['matched_workflow_title'] = t.get('pending_workflow_prompt_title')
                    t['matched_workflow_color'] = t.get('pending_workflow_prompt_color')
                    
                    # These are null if no pre-applied workflow or if workflow ran and llm_op_id is set
                    t['llm_operation_result'] = None
                    t['llm_operation_error'] = None
                    t['llm_operation_ran_at'] = None
                    t['llm_operation_prompt_id'] = None 
                    t['llm_operation_provider'] = None


            if total_pages > 1 or total_items > min(PER_PAGE_OPTIONS):
                pagination = {
                    'current_page': page, 'total_pages': total_pages,
                    'has_prev': page > 1, 'has_next': page < total_pages,
                    'total_items': total_items, 'per_page': per_page
                }
                logging.debug(f"{log_prefix} Pagination active: Page {page}/{total_pages}, Total Items: {total_items}")
            else:
                 logging.debug(f"{log_prefix} Pagination not needed: Total Items: {total_items}")
        else:
             logging.debug(f"{log_prefix} No visible transcriptions found for user.")

    except Exception as e:
        logging.error(f"{log_prefix} Error fetching paginated transcriptions: {e}", exc_info=True)

    filter_query = history_filters.to_query()

    def history_url(**changes):
        """URL of the history with the current filters, changed by ``changes``.
        A value of None removes that parameter. The page resets to 1 unless given."""
        params = dict(filter_query)
        params.update(changes)
        if 'page' in params and (params['page'] is None or params['page'] <= 1):
            params.pop('page')
        params = {key: value for key, value in params.items() if value is not None}
        return url_for('main.index', **params) + '#history'

    return render_template(
        'index.html',
        effective_default_api=effective_default_api,
        effective_default_language=effective_default_language,
        supported_languages=supported_languages,
        transcriptions=transcriptions,
        pagination=pagination,
        history_filters=history_filters,
        history_filter_query=filter_query,
        history_filter_options=filter_options,
        history_date_presets=history_filter_service.date_preset_options(_),
        history_duration_max=DURATION_MAX,
        history_duration_step=DURATION_STEP,
        history_per_page=per_page,
        history_per_page_options=PER_PAGE_OPTIONS,
        history_filtered_total=filtered_total,
        history_unfiltered_total=unfiltered_total,
        history_url=history_url,
    )


@main_bp.route('/live')
@login_required
def live():
    """Render the full-screen live transcription workspace."""
    if (
        current_app.config['DEPLOYMENT_MODE'] == 'multi'
        and not (
            check_permission(current_user, 'use_api_openai')
            or check_permission(current_user, 'use_api_openai_live_transcribe')
            or check_permission(current_user, 'use_api_openrouter')
            or check_permission(current_user, 'use_api_google_gemini')
        )
    ):
        abort(403)
    return render_template(
        'live.html',
        live_languages=transcription_catalog_model.get_language_map(),
    )

@main_bp.route('/manage-prompts')
@login_required
def manage_prompts():
    """Renders the page for users to manage their saved workflow prompts."""
    log_prefix = f"[ROUTE:Main:ManagePrompts:User:{current_user.id}]"
    logging.debug(f"{log_prefix} Accessing route '/manage-prompts'.")

    if not current_user.has_permission('allow_workflows'):
        logging.warning(f"{log_prefix} Access denied: User lacks 'allow_workflows' permission.")
        abort(403)

    return render_template('manage_prompts.html', title="Manage Workflow Prompts")

@main_bp.route('/set-language/<lang>')
def set_language(lang):
    """Sets the language for the user's session."""
    log_prefix = "[ROUTE:Main:SetLanguage]"
    # Validate the language code against the supported languages
    if lang in current_app.config['SUPPORTED_LANGUAGES']:
        session['language'] = lang
        logging.info(f"{log_prefix} Language set to '{lang}' in session.")
    else:
        logging.warning(f"{log_prefix} Attempted to set unsupported language: '{lang}'.")

    # Redirect back to the page the user came from, or to the index page as a fallback
    referrer = request.referrer
    if referrer:
        return redirect(referrer)
    return redirect(url_for('main.index'))
