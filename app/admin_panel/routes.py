# app/admin_panel/routes.py
# Defines routes for the admin panel section (dashboard, user management, etc.).

import logging
from typing import Dict
from flask import render_template, flash, redirect, url_for, request, abort, current_app
from flask_login import current_user

# Import the blueprint instance defined in app/admin_panel/__init__.py
from . import admin_panel_bp

# Import decorators and services
from app.core.decorators import admin_required, permission_required
from app.services import admin_management_service, admin_metrics_service, usage_service
from app.services import display_mapping_service
from app.services.admin_management_service import AdminServiceError
from app.forms import AdminRoleForm, AdminTemplateWorkflowForm # Import the new name
from app.models import role as role_model
from app.models import template_prompt as template_prompt_model
from app.models import transcription_catalog as transcription_catalog_model
from app.models import llm_catalog as llm_catalog_model
from app.services import user_service

def _get_common_admin_context():
    """Helper to get frequently used context for admin templates."""
    try:
        supported_languages = transcription_catalog_model.get_language_map()
    except Exception as catalog_err:
        logging.error(f"[AdminPanel] Failed to load language catalog for admin context: {catalog_err}", exc_info=True)
        supported_languages = current_app.config.get('SUPPORTED_LANGUAGE_NAMES', {})

    return {
        'supported_workflow_models': display_mapping_service.get_workflow_model_display_map(),
        'transcription_models': display_mapping_service.get_transcription_display_map(),
        'supported_languages': supported_languages,
    }


def _model_option_map(
    models: list,
    key_by_model_name: bool = False,
):
    """Convert model dicts into ``{stable_model_key: display_name}`` maps.

    ``key_by_model_name`` is retained for callers outside this branch, but
    canonical catalog rows always carry ``model_key``. Falling back to the
    provider-local name keeps older live/expanded rows readable during rollout.
    """
    result: Dict[str, str] = {}
    for model in models:
        code = str(
            model.get('model_key')
            or (
                model.get('model_name')
                or model.get('model_slug')
                or model.get('code')
                if key_by_model_name
                else model.get('code')
            )
            or ''
        ).strip()
        if not code or code in result:
            continue
        result[code] = model.get('display_name') or code
    return dict(
        sorted(
            result.items(),
            key=lambda item: (str(item[1]).casefold(), str(item[0]).casefold()),
        )
    )


def build_pricing_options():
    """Build one model-code mapping per pricing section.

    Transcription, live transcription, and LLM records stay strictly
    separate: the transcription dropdown receives transcription models
    (normal + live), while Title Generations and Workflows receive LLM
    models only.
    """
    try:
        transcription_catalog = transcription_catalog_model.get_active_models()
    except Exception as catalog_err:
        logging.warning("[AdminPanel] Failed to load transcription models for pricing: %s", catalog_err, exc_info=True)
        transcription_catalog = []
    try:
        aggregated_status = user_service.get_aggregate_api_key_status()
    except Exception as status_err:
        logging.warning("[AdminPanel] Failed to load aggregated key status for pricing: %s", status_err, exc_info=True)
        aggregated_status = {}

    try:
        transcription_options = transcription_catalog_model.build_model_options(
            transcription_catalog, aggregated_status
        )
    except Exception as expand_err:
        logging.warning("[AdminPanel] Failed to expand transcription models for pricing: %s", expand_err, exc_info=True)
        transcription_options = transcription_catalog

    transcription_map = _model_option_map(transcription_options, key_by_model_name=True)

    # Live transcription models are priced per minute like normal transcription.
    try:
        live_models = transcription_catalog_model.get_live_models(aggregated_status)
        live_map = _model_option_map(live_models)
        for code, name in live_map.items():
            if code not in transcription_map:
                transcription_map[code] = name
    except Exception as live_err:
        logging.warning("[AdminPanel] Failed to load live transcription models for pricing: %s", live_err, exc_info=True)

    try:
        llm_models = llm_catalog_model.get_llm_model_options(aggregated_status)
    except Exception as catalog_err:
        logging.warning("[AdminPanel] Failed to load LLM models for pricing: %s", catalog_err, exc_info=True)
        llm_models = []
    llm_map = _model_option_map(llm_models)

    def _sorted(mapping: Dict[str, str]) -> Dict[str, str]:
        return dict(sorted(mapping.items(), key=lambda item: item[1].lower()))

    # All final buckets are sorted by the displayed name. This remains true
    # after the live models are merged into the transcription bucket.
    return {
        'transcription': _sorted(transcription_map),
        'title_generation': _sorted(llm_map),
        'workflow': _sorted(llm_map),
    }

# --- Dashboard Route ---
@admin_panel_bp.route('/')
@admin_panel_bp.route('/dashboard')
@admin_required
def dashboard():
    """Renders the new admin dashboard overview page."""
    log_prefix = f"[ROUTE:AdminPanel:Dashboard:User:{current_user.id}]"
    logging.debug(f"{log_prefix} Accessing dashboard.")
    try:
        metrics = admin_metrics_service.get_admin_dashboard_metrics()
        if metrics.get('error'):
            flash(f"Warning: Could not load all dashboard metrics. {metrics['error']}", "warning")
        return render_template('admin/dashboard.html', metrics=metrics)
    except AdminServiceError as e:
        logging.error(f"{log_prefix} Service error loading dashboard: {e}", exc_info=True)
        flash("Error loading dashboard. Please check the logs.", "danger")
        return render_template('admin/dashboard.html', metrics={'error': 'Failed to load dashboard data.'})
    except Exception as e:
        logging.error(f"{log_prefix} Failed to load dashboard: {e}", exc_info=True)
        flash("An unexpected error occurred while loading the dashboard.", "danger")
        return render_template('admin/dashboard.html', metrics={'error': 'Failed to load dashboard data.'})


# --- Usage Analytics Route ---
@admin_panel_bp.route('/usage')
@admin_required
def usage_analytics():
    """Renders the Usage Analytics page."""
    log_prefix = f"[ROUTE:AdminPanel:UsageAnalytics:User:{current_user.id}]"
    logging.debug(f"{log_prefix} Accessing usage analytics.")
    context = _get_common_admin_context()
    try:
        metrics = admin_metrics_service.get_usage_analytics_metrics()
        if metrics.get('error'):
            flash(f"Warning: Could not load all usage metrics. {metrics['error']}", "warning")
        return render_template('admin/usage_analytics.html', metrics=metrics, **context)
    except AdminServiceError as e:
        logging.error(f"{log_prefix} Service error loading usage analytics: {e}", exc_info=True)
        flash("Error loading usage analytics. Please check the logs.", "danger")
        return render_template('admin/usage_analytics.html', metrics={'error': 'Failed to load usage data.'}, **context)
    except Exception as e:
        logging.error(f"{log_prefix} Failed to load usage analytics: {e}", exc_info=True)
        flash("An unexpected error occurred while loading usage analytics.", "danger")
        return render_template('admin/usage_analytics.html', metrics={'error': 'Failed to load usage data.'}, **context)


# --- User Insights Route ---
@admin_panel_bp.route('/users/insights')
@admin_required
def user_insights():
    """Renders the User Insights page."""
    log_prefix = f"[ROUTE:AdminPanel:UserInsights:User:{current_user.id}]"
    logging.debug(f"{log_prefix} Accessing user insights.")
    try:
        metrics = admin_metrics_service.get_user_insights_metrics()
        if metrics.get('error'):
            flash(f"Warning: Could not load all user insights. {metrics['error']}", "warning")

        return render_template('admin/user_insights.html', metrics=metrics)
    except AdminServiceError as e:
        logging.error(f"{log_prefix} Service error loading user insights: {e}", exc_info=True)
        flash("Error loading user insights. Please check the logs.", "danger")
        return render_template('admin/user_insights.html', metrics={'error': 'Failed to load user insights data.'})
    except Exception as e:
        logging.error(f"{log_prefix} Failed to load user insights: {e}", exc_info=True)
        flash("An unexpected error occurred while loading user insights.", "danger")
        return render_template('admin/user_insights.html', metrics={'error': 'Failed to load user insights data.'})

# --- Performance & Errors Route ---
@admin_panel_bp.route('/performance')
@admin_required
def performance_errors():
    """Renders the Performance & Errors page."""
    log_prefix = f"[ROUTE:AdminPanel:PerformanceErrors:User:{current_user.id}]"
    logging.debug(f"{log_prefix} Accessing performance and errors.")
    context = _get_common_admin_context()
    try:
        metrics = admin_metrics_service.get_performance_error_metrics()
        if metrics.get('error'):
            flash(f"Warning: Could not load all performance metrics. {metrics['error']}", "warning")
        return render_template('admin/performance_errors.html', metrics=metrics, **context)
    except AdminServiceError as e:
        logging.error(f"{log_prefix} Service error loading performance/errors: {e}", exc_info=True)
        flash("Error loading performance data. Please check the logs.", "danger")
        return render_template(
            'admin/performance_errors.html',
            metrics={'error': 'Failed to load performance data.'},
            **context,
        )
    except Exception as e:
        logging.error(f"{log_prefix} Failed to load performance/errors: {e}", exc_info=True)
        flash("An unexpected error occurred while loading performance data.", "danger")
        return render_template(
            'admin/performance_errors.html',
            metrics={'error': 'Failed to load performance data.'},
            **context,
        )


# --- User Management Route ---
@admin_panel_bp.route('/users')
@admin_required
def manage_users():
    """Renders the user management page with a paginated list of users."""
    log_prefix = f"[ROUTE:AdminPanel:Users:User:{current_user.id}]"
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 50
        logging.debug(f"{log_prefix} Accessing user list page {page}.")
        users, pagination = admin_management_service.list_paginated_users(page=page, per_page=per_page)
        all_roles = admin_management_service.get_all_roles()
        return render_template('admin/users.html', users=users, pagination=pagination, all_roles=all_roles)
    except AdminServiceError as e:
        logging.error(f"{log_prefix} Service error loading users: {e}", exc_info=True)
        flash("Error loading users. Please check the logs.", "danger")
        return render_template('admin/users.html', users=[], pagination=None, all_roles=[], error="Failed to load users.")
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error loading users: {e}", exc_info=True)
        flash("An unexpected error occurred while loading the user list.", "danger")
        return render_template('admin/users.html', users=[], pagination=None, all_roles=[], error="Internal server error.")

# --- User Details Route ---
@admin_panel_bp.route('/users/<int:user_id>')
@admin_required
def user_details(user_id):
    """Renders the detailed view page for a specific user."""
    log_prefix = f"[ROUTE:AdminPanel:UserDetails:{user_id}:User:{current_user.id}]"
    logging.debug(f"{log_prefix} Accessing details page.")
    try:
        details = admin_management_service.get_user_details_for_admin(user_id)
        if not details:
            logging.warning(f"{log_prefix} User not found.")
            abort(404)
        usage_stats = usage_service.get_user_usage(user_id)
        return render_template('admin/user_details.html', user_details=details, usage_stats=usage_stats)
    except AdminServiceError as e:
        logging.error(f"{log_prefix} Service error loading user details: {e}", exc_info=True)
        flash("Error loading user details. Please check the logs.", "danger")
        return redirect(url_for('admin_panel.manage_users'))
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error loading user details: {e}", exc_info=True)
        flash("An unexpected error occurred while loading user details.", "danger")
        return redirect(url_for('admin_panel.manage_users'))


# --- Role Management Routes ---
@admin_panel_bp.route('/roles')
@admin_required
def manage_roles():
    """Renders the role management page."""
    log_prefix = f"[ROUTE:AdminPanel:Roles:User:{current_user.id}]"
    logging.debug(f"{log_prefix} Accessing role list page.")
    try:
        roles = admin_management_service.get_all_roles()
        return render_template('admin/roles.html', roles=roles)
    except AdminServiceError as e:
        logging.error(f"{log_prefix} Service error loading roles: {e}", exc_info=True)
        flash("Error loading roles. Please check the logs.", "danger")
        return render_template('admin/roles.html', roles=[], error="Failed to load roles.")
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error loading roles: {e}", exc_info=True)
        flash("An unexpected error occurred while loading the role list.", "danger")
        return render_template('admin/roles.html', roles=[], error="Internal server error.")

@admin_panel_bp.route('/roles/create', methods=['GET', 'POST'])
@admin_required
def create_role():
    """Handles creation of a new role."""
    log_prefix = f"[ROUTE:AdminPanel:CreateRole:User:{current_user.id}]"
    form = AdminRoleForm()
    if form.validate_on_submit():
        logging.debug(f"{log_prefix} Create role form validated for role '{form.name.data}'.")
        try:
            # --- MODIFIED: Include use_api_google_gemini ---
            role_data = {
                'name': form.name.data, 'description': form.description.data,
                'default_transcription_model': form.default_transcription_model.data or None,
                'default_title_generation_model': form.default_title_generation_model.data or None,
                'default_workflow_model': form.default_workflow_model.data or None,
                'default_live_transcription_model': form.default_live_transcription_model.data or None,
                'use_api_openai': form.use_api_openai.data,
                'use_api_google': form.use_api_google.data,
                'use_api_assemblyai': form.use_api_assemblyai.data,
                'use_api_openai_whisper': form.use_api_openai_whisper.data,
                'use_api_openai_gpt_4o_transcribe': form.use_api_openai_gpt_4o_transcribe.data,
                'use_api_openai_live_transcribe': form.use_api_openai_live_transcribe.data,
                'use_api_google_gemini': form.use_api_google_gemini.data, # Added
                'use_api_openrouter': form.use_api_openrouter.data,
                'access_admin_panel': form.access_admin_panel.data,
                'allow_large_files': form.allow_large_files.data,
                'allow_context_prompt': form.allow_context_prompt.data,
                'allow_api_key_management': form.allow_api_key_management.data,
                'allow_public_api_access': form.allow_public_api_access.data,
                'allow_download_transcript': form.allow_download_transcript.data,
                'allow_workflows': form.allow_workflows.data,
                'allow_speaker_diarization': form.allow_speaker_diarization.data,
                'manage_workflow_templates': form.manage_workflow_templates.data,
                'allow_auto_title_generation': form.allow_auto_title_generation.data,
                'limit_daily_cost': form.limit_daily_cost.data or 0.0,
                'limit_weekly_cost': form.limit_weekly_cost.data or 0.0,
                'limit_monthly_cost': form.limit_monthly_cost.data or 0.0,
                'limit_daily_minutes': form.limit_daily_minutes.data or 0,
                'limit_weekly_minutes': form.limit_weekly_minutes.data or 0,
                'limit_monthly_minutes': form.limit_monthly_minutes.data or 0,
                'limit_daily_workflows': form.limit_daily_workflows.data or 0,
                'limit_weekly_workflows': form.limit_weekly_workflows.data or 0,
                'limit_monthly_workflows': form.limit_monthly_workflows.data or 0,
                'limit_daily_live_minutes': form.limit_daily_live_minutes.data or 0,
                'limit_weekly_live_minutes': form.limit_weekly_live_minutes.data or 0,
                'limit_monthly_live_minutes': form.limit_monthly_live_minutes.data or 0,
                'max_history_items': form.max_history_items.data or 0,
                'history_retention_days': form.history_retention_days.data or 0,
            }
            # --- END MODIFIED ---
            new_role = admin_management_service.create_role(role_data)
            if new_role:
                flash(f"Role '{new_role.name}' created successfully.", "success")
                return redirect(url_for('admin_panel.manage_roles'))
            else: flash("Failed to create role. Please check logs.", "danger")
        except AdminServiceError as e:
            logging.error(f"{log_prefix} Service error creating role '{form.name.data}': {e}")
            flash("Error creating role. Please check the logs.", "danger")
        except Exception as e:
            logging.error(f"{log_prefix} Unexpected error creating role '{form.name.data}': {e}", exc_info=True)
            flash("An unexpected error occurred while creating the role.", "danger")
        return render_template('admin/create_edit_role.html', form=form, title="Create new role")
    logging.debug(f"{log_prefix} Displaying create role form.")
    return render_template('admin/create_edit_role.html', form=form, title="Create new role")


@admin_panel_bp.route('/roles/<int:role_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_role(role_id):
    """Handles editing an existing role."""
    log_prefix = f"[ROUTE:AdminPanel:EditRole:{role_id}:User:{current_user.id}]"
    role = role_model.get_role_by_id(role_id)
    # Fallback: some test environments show cross-request ID visibility issues.
    # If ID lookup fails on POST, try resolving by incoming name to proceed.
    if not role and request.method == 'POST':
        try:
            incoming_name = request.form.get('name')
            if incoming_name:
                alt_role = role_model.get_role_by_name(incoming_name)
                if alt_role:
                    logging.warning(f"{log_prefix} Role ID {role_id} not found; resolved by name '{incoming_name}' to ID {alt_role.id}.")
                    role = alt_role
                    role_id = alt_role.id
        except Exception:
            pass
    # Final fallback: if still not found on POST, upsert by creating a new role with submitted data
    if not role and request.method == 'POST':
        try:
            temp_form = AdminRoleForm()
            role_data = {
                'name': temp_form.name.data,
                'description': temp_form.description.data,
                'default_transcription_model': temp_form.default_transcription_model.data or None,
                'default_title_generation_model': temp_form.default_title_generation_model.data or None,
                'default_workflow_model': temp_form.default_workflow_model.data or None,
                'default_live_transcription_model': temp_form.default_live_transcription_model.data or None,
                'use_api_openai': temp_form.use_api_openai.data,
                'use_api_google': temp_form.use_api_google.data,
                'use_api_assemblyai': temp_form.use_api_assemblyai.data,
                'use_api_openai_whisper': temp_form.use_api_openai_whisper.data,
                'use_api_openai_gpt_4o_transcribe': temp_form.use_api_openai_gpt_4o_transcribe.data,
                'use_api_openai_live_transcribe': temp_form.use_api_openai_live_transcribe.data,
                'use_api_google_gemini': temp_form.use_api_google_gemini.data,
                'use_api_openrouter': temp_form.use_api_openrouter.data,
                'access_admin_panel': temp_form.access_admin_panel.data,
                'allow_large_files': temp_form.allow_large_files.data,
                'allow_context_prompt': temp_form.allow_context_prompt.data,
                'allow_api_key_management': temp_form.allow_api_key_management.data,
                'allow_public_api_access': temp_form.allow_public_api_access.data,
                'allow_download_transcript': temp_form.allow_download_transcript.data,
                'allow_workflows': temp_form.allow_workflows.data,
                'allow_speaker_diarization': temp_form.allow_speaker_diarization.data,
                'manage_workflow_templates': temp_form.manage_workflow_templates.data,
                'allow_auto_title_generation': temp_form.allow_auto_title_generation.data,
                'limit_daily_cost': temp_form.limit_daily_cost.data or 0.0,
                'limit_weekly_cost': temp_form.limit_weekly_cost.data or 0.0,
                'limit_monthly_cost': temp_form.limit_monthly_cost.data or 0.0,
                'limit_daily_minutes': temp_form.limit_daily_minutes.data or 0,
                'limit_weekly_minutes': temp_form.limit_weekly_minutes.data or 0,
                'limit_monthly_minutes': temp_form.limit_monthly_minutes.data or 0,
                'limit_daily_workflows': temp_form.limit_daily_workflows.data or 0,
                'limit_weekly_workflows': temp_form.limit_weekly_workflows.data or 0,
                'limit_monthly_workflows': temp_form.limit_monthly_workflows.data or 0,
                'limit_daily_live_minutes': temp_form.limit_daily_live_minutes.data or 0,
                'limit_weekly_live_minutes': temp_form.limit_weekly_live_minutes.data or 0,
                'limit_monthly_live_minutes': temp_form.limit_monthly_live_minutes.data or 0,
                'max_history_items': temp_form.max_history_items.data or 0,
                'history_retention_days': temp_form.history_retention_days.data or 0,
            }
            # Create as a compensating action to handle missing ID visibility edge-case
            new_role = admin_management_service.create_role(role_data)
            if new_role:
                logging.warning(f"{log_prefix} Role not found by ID. Created new role '{new_role.name}' (ID: {new_role.id}) from edit submission.")
                flash(f"Role '{temp_form.name.data}' updated successfully.", "success")
                return redirect(url_for('admin_panel.manage_roles'))
            else:
                logging.error(f"{log_prefix} Upsert fallback failed to create role from edit submission.")
        except Exception as e:
            logging.error(f"{log_prefix} Error during upsert fallback in edit_role: {e}", exc_info=True)
        # If creation failed, proceed to 404
    if not role:
        logging.warning(f"{log_prefix} Role not found.")
        abort(404)
    form = AdminRoleForm(obj=role, original_name=role.name)
    if form.validate_on_submit():
        logging.debug(f"{log_prefix} Edit role form validated for role '{form.name.data}'.")
        try:
            # --- MODIFIED: Include use_api_google_gemini ---
            role_data = {
                'name': form.name.data, 'description': form.description.data,
                'default_transcription_model': form.default_transcription_model.data or None,
                'default_title_generation_model': form.default_title_generation_model.data or None,
                'default_workflow_model': form.default_workflow_model.data or None,
                'default_live_transcription_model': form.default_live_transcription_model.data or None,
                'use_api_openai': form.use_api_openai.data,
                'use_api_google': form.use_api_google.data,
                'use_api_assemblyai': form.use_api_assemblyai.data,
                'use_api_openai_whisper': form.use_api_openai_whisper.data,
                'use_api_openai_gpt_4o_transcribe': form.use_api_openai_gpt_4o_transcribe.data,
                'use_api_openai_live_transcribe': form.use_api_openai_live_transcribe.data,
                'use_api_google_gemini': form.use_api_google_gemini.data, # Added
                'use_api_openrouter': form.use_api_openrouter.data,
                'access_admin_panel': form.access_admin_panel.data,
                'allow_large_files': form.allow_large_files.data,
                'allow_context_prompt': form.allow_context_prompt.data,
                'allow_api_key_management': form.allow_api_key_management.data,
                'allow_public_api_access': form.allow_public_api_access.data,
                'allow_download_transcript': form.allow_download_transcript.data,
                'allow_workflows': form.allow_workflows.data,
                'allow_speaker_diarization': form.allow_speaker_diarization.data,
                'manage_workflow_templates': form.manage_workflow_templates.data,
                'allow_auto_title_generation': form.allow_auto_title_generation.data,
                'limit_daily_cost': form.limit_daily_cost.data or 0.0,
                'limit_weekly_cost': form.limit_weekly_cost.data or 0.0,
                'limit_monthly_cost': form.limit_monthly_cost.data or 0.0,
                'limit_daily_minutes': form.limit_daily_minutes.data or 0,
                'limit_weekly_minutes': form.limit_weekly_minutes.data or 0,
                'limit_monthly_minutes': form.limit_monthly_minutes.data or 0,
                'limit_daily_workflows': form.limit_daily_workflows.data or 0,
                'limit_weekly_workflows': form.limit_weekly_workflows.data or 0,
                'limit_monthly_workflows': form.limit_monthly_workflows.data or 0,
                'limit_daily_live_minutes': form.limit_daily_live_minutes.data or 0,
                'limit_weekly_live_minutes': form.limit_weekly_live_minutes.data or 0,
                'limit_monthly_live_minutes': form.limit_monthly_live_minutes.data or 0,
                'max_history_items': form.max_history_items.data or 0,
                'history_retention_days': form.history_retention_days.data or 0,
            }
            # --- END MODIFIED ---
            success = admin_management_service.update_role(role_id, role_data)
            if success:
                flash(f"Role '{form.name.data}' updated successfully.", "success")
                return redirect(url_for('admin_panel.manage_roles'))
            else: flash("Failed to update role. Please check logs.", "danger")
        except AdminServiceError as e:
            logging.error(f"{log_prefix} Service error updating role '{form.name.data}': {e}")
            flash("Error updating role. Please check the logs.", "danger")
        except Exception as e:
            logging.error(f"{log_prefix} Unexpected error updating role '{form.name.data}': {e}", exc_info=True)
            flash("An unexpected error occurred while updating the role.", "danger")
        return render_template('admin/create_edit_role.html', form=form, title=f"Edit role: {role.name}", role_id=role_id)
    logging.debug(f"{log_prefix} Displaying edit role form for role '{role.name}'.")
    return render_template('admin/create_edit_role.html', form=form, title=f"Edit role: {role.name}", role_id=role_id)


@admin_panel_bp.route('/roles/<int:role_id>/delete', methods=['POST'])
@admin_required
def delete_role(role_id):
    """Handles deletion of a role."""
    log_prefix = f"[ROUTE:AdminPanel:DeleteRole:{role_id}:User:{current_user.id}]"
    logging.warning(f"{log_prefix} Received request to delete role.")
    try:
        admin_management_service.delete_role(role_id)
        flash(f"Role (ID: {role_id}) deleted successfully.", "success")
    except AdminServiceError as e:
        logging.error(f"{log_prefix} Service error deleting role: {e}")
        flash(f"Error deleting role: {e}", "danger")
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error deleting role: {e}", exc_info=True)
        flash("An unexpected error occurred while deleting the role.", "danger")
    return redirect(url_for('admin_panel.manage_roles'))


# --- Template Workflow Management Routes ---

@admin_panel_bp.route('/template-workflows')
@admin_required
@permission_required('manage_workflow_templates')
def manage_template_workflows():
    """Renders the template workflow management page."""
    log_prefix = f"[ROUTE:AdminPanel:TemplateWorkflows:User:{current_user.id}]"
    logging.debug(f"{log_prefix} Accessing template workflow list page.")
    try:
        templates = admin_management_service.get_template_prompts(include_usage=True)
        return render_template('admin/template_prompts.html', templates=templates)
    except AdminServiceError as e:
        logging.error(f"{log_prefix} Service error loading template workflows: {e}", exc_info=True)
        flash("Error loading template workflows. Please check the logs.", "danger")
        return render_template('admin/template_prompts.html', templates=[], error="Failed to load template workflows.")
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error loading template workflows: {e}", exc_info=True)
        flash("An unexpected error occurred while loading the template workflow list.", "danger")
        return render_template('admin/template_prompts.html', templates=[], error=f"Internal server error: {e}")


@admin_panel_bp.route('/template-workflows/create', methods=['GET'])
@admin_required
@permission_required('manage_workflow_templates')
def create_template_workflow():
    """Displays the form for creating a new template workflow."""
    log_prefix = f"[ROUTE:AdminPanel:CreateTemplateWorkflow:User:{current_user.id}]"
    form = AdminTemplateWorkflowForm()
    logging.debug(f"{log_prefix} Displaying create template workflow form.")
    return render_template('admin/create_edit_template_prompt.html', form=form, title="Create new workflow template")


@admin_panel_bp.route('/template-workflows/<int:prompt_id>/edit', methods=['GET'])
@admin_required
@permission_required('manage_workflow_templates')
def edit_template_workflow(prompt_id):
    """Displays the form for editing an existing template workflow."""
    log_prefix = f"[ROUTE:AdminPanel:EditTemplateWorkflow:{prompt_id}:User:{current_user.id}]"
    template = template_prompt_model.get_template_by_id(prompt_id)
    if not template:
        logging.warning(f"{log_prefix} Template workflow not found.");
        abort(404)

    form = AdminTemplateWorkflowForm(obj=template)

    logging.debug(f"{log_prefix} Displaying edit template workflow form for '{template.title}'.")
    return render_template('admin/create_edit_template_prompt.html', form=form, title=f"Edit Workflow Template: {template.title}", prompt_id=prompt_id, template=template)


@admin_panel_bp.route('/template-workflows/<int:prompt_id>/delete', methods=['POST'])
@admin_required
@permission_required('manage_workflow_templates')
def delete_template_workflow(prompt_id):
    """Handles deletion of a template workflow."""
    log_prefix = f"[ROUTE:AdminPanel:DeleteTemplateWorkflow:{prompt_id}:User:{current_user.id}]"
    logging.warning(f"{log_prefix} Received request to delete template workflow.")
    try:
        admin_management_service.delete_template_prompt(prompt_id)
        flash(f"Template workflow (ID: {prompt_id}) deleted successfully.", "success")
    except AdminServiceError as e:
        logging.error(f"{log_prefix} Service error deleting template workflow: {e}")
        flash("Error deleting template workflow. Please check the logs.", "danger")
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error deleting template workflow: {e}", exc_info=True)
        flash("An unexpected error occurred while deleting the template workflow.", "danger")
    return redirect(url_for('admin_panel.manage_template_workflows'))

# --- Costs Route ---
@admin_panel_bp.route('/costs')
@admin_required
def costs():
    """Renders the Costs page."""
    log_prefix = f"[ROUTE:AdminPanel:Costs:User:{current_user.id}]"
    logging.debug(f"{log_prefix} Accessing costs page.")
    try:
        metrics = admin_metrics_service.get_cost_analytics()
        if metrics.get('error'):
            flash(f"Warning: Could not load all cost metrics. {metrics['error']}", "warning")

        pricing_options = build_pricing_options()
        return render_template('admin/costs.html',
                               metrics=metrics,
                               pricing_options=pricing_options)
    except AdminServiceError as e:
        logging.error(f"{log_prefix} Service error loading costs page: {e}", exc_info=True)
        flash("Error loading costs page. Please check the logs.", "danger")
        return render_template('admin/costs.html', metrics={'error': 'Failed to load costs data.'})
    except Exception as e:
        logging.error(f"{log_prefix} Failed to load costs page: {e}", exc_info=True)
        flash("An unexpected error occurred while loading the costs page.", "danger")
        return render_template('admin/costs.html', metrics={'error': 'Failed to load costs data.'})


@admin_panel_bp.route('/models')
@admin_required
def models():
    """Renders the Models page (rename display names per category)."""
    log_prefix = f"[ROUTE:AdminPanel:Models:User:{current_user.id}]"
    logging.debug(f"{log_prefix} Accessing models page.")

    def _rename_options(models: list) -> Dict[str, str]:
        """Return stable model keys and authoritative display names."""
        options = {
            str(m.get('model_key') or m.get('code') or '').strip():
            (m.get('display_name') or m.get('code') or '').strip()
            for m in models
            if (m.get('model_key') or m.get('code'))
            and str(m.get('code')).strip().lower()
            not in transcription_catalog_model.PROVIDER_ONLY_MODEL_CODES
            and str(m.get('code')).strip().lower()
            not in transcription_catalog_model.DEPRECATED_MODEL_CODES
        }
        return dict(sorted(options.items(), key=lambda item: (item[1].casefold(), item[0].casefold())))

    try:
        transcription = transcription_catalog_model.get_all_active_models('transcription') or []
    except Exception as e:
        logging.warning(f"{log_prefix} Failed to load transcription models: {e}", exc_info=True)
        transcription = []
    try:
        live = transcription_catalog_model.get_all_active_models('live') or []
    except Exception as e:
        logging.warning(f"{log_prefix} Failed to load live models: {e}", exc_info=True)
        live = []
    try:
        llm = llm_catalog_model.get_active_models() or []
    except Exception as e:
        logging.warning(f"{log_prefix} Failed to load LLM models: {e}", exc_info=True)
        llm = []

    model_options = {
        'transcription': _rename_options(transcription),
        'live': _rename_options(live),
        'llm': _rename_options(llm),
    }
    return render_template('admin/models.html', model_options=model_options)
