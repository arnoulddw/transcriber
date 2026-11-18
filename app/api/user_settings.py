# app/api/user_settings.py
# Defines the Blueprint for user-specific settings API endpoints (e.g., API keys, readiness, profile).

import logging
from typing import List
from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from flask_babel import gettext as _

# Import forms and services
from app.forms import ApiKeyForm, UserProfileForm, ChangePasswordForm
from app.services import user_service, auth_service, admin_management_service, usage_service
from app.services.live_transcription_service import LIVE_MINUTES_RESERVATION
from app.services.user_service import (
    KeyNotFoundError, DatabaseUpdateError, UserNotFoundError, ApiKeyManagementError,
    ProfileUpdateError, UsernameTakenError, EmailTakenError,
    PromptManagementError, PromptNotFoundError, DuplicatePromptError, DataLengthError
)
from app.services.auth_service import InvalidCredentialsError, AuthServiceError
from app.services.admin_management_service import AdminServiceError
from app.models.user import User 
from app.models import user, user_prompt as user_prompt_model
from app.models.user_prompt import UserPrompt
from app.models import transcription as transcription_model 
from app.core.decorators import check_permission, permission_required
from app.extensions import limiter
from app.services import access_service

# Define the Blueprint
user_settings_bp = Blueprint('user_settings', __name__, url_prefix='/api/user') 

# --- User Readiness Endpoint ---
@user_settings_bp.route('/readiness', methods=['GET'])
@login_required
@limiter.exempt
def get_user_readiness():
    """
    API endpoint to get the user's readiness status for transcription.
    Includes API key status, relevant permissions, usage limits, and current usage stats.
    Crucial for the frontend to determine available actions and display limits.
    """
    user_obj: User = current_user 
    user_id = user_obj.id
    log_prefix = f"[API:Readiness:User:{user_id}]"
    logging.debug(f"{log_prefix} Request received.")

    try:
        # This is a good place to ensure the user's templates are up-to-date
        # as it's called frequently when the user is active on the main page.
        user_service.sync_templates_for_user(user_id)

        key_status = user_service.get_user_api_key_status(user_id)
        if access_service.is_personal_mode():
            key_status = access_service.merge_env_provider_keys(key_status)

        permissions = {}
        limits = {}
        if user_obj.role: 
            role = user_obj.role 
            permissions = {
                'use_api_assemblyai': role.has_permission('use_api_assemblyai'),
                'use_api_openai': role.has_permission('use_api_openai'),
                'use_api_openai_whisper': role.has_permission('use_api_openai_whisper'),
                'use_api_openai_gpt_4o_transcribe': role.has_permission('use_api_openai_gpt_4o_transcribe'),
                'use_api_openai_live_transcribe': role.has_permission('use_api_openai_live_transcribe'),
                'use_api_google_gemini': role.has_permission('use_api_google_gemini'),
                'use_api_google': role.has_permission('use_api_google'),
                'use_api_openrouter': role.has_permission('use_api_openrouter'),
                'allow_large_files': role.has_permission('allow_large_files'),
                'allow_context_prompt': role.has_permission('allow_context_prompt'),
                'allow_download_transcript': role.has_permission('allow_download_transcript'),
                'allow_api_key_management': role.has_permission('allow_api_key_management'), 
                'allow_public_api_access': role.has_permission('allow_public_api_access'),
                'access_admin_panel': access_service.can_access_admin_panel(user_obj),
                'allow_workflows': role.has_permission('allow_workflows'), 
                'manage_workflow_templates': role.has_permission('manage_workflow_templates'), 
                'allow_auto_title_generation': role.has_permission('allow_auto_title_generation'),
                'allow_speaker_diarization': role.has_permission('allow_speaker_diarization')
            }
            limits = {
                'limit_daily_cost': role.get_limit('limit_daily_cost'),
                'limit_weekly_cost': role.get_limit('limit_weekly_cost'),
                'limit_monthly_cost': role.get_limit('limit_monthly_cost'),
                'limit_daily_minutes': role.get_limit('limit_daily_minutes'),
                'limit_weekly_minutes': role.get_limit('limit_weekly_minutes'),
                'limit_monthly_minutes': role.get_limit('limit_monthly_minutes'),
                'limit_daily_workflows': role.get_limit('limit_daily_workflows'),
                'limit_weekly_workflows': role.get_limit('limit_weekly_workflows'),
                'limit_monthly_workflows': role.get_limit('limit_monthly_workflows'),
                'limit_daily_live_minutes': role.get_limit('limit_daily_live_minutes'),
                'limit_weekly_live_minutes': role.get_limit('limit_weekly_live_minutes'),
                'limit_monthly_live_minutes': role.get_limit('limit_monthly_live_minutes'),
            }
        else:
            logging.warning(f"{log_prefix} User has no role assigned. Permissions/limits will be empty.")

        usage_stats = usage_service.get_user_usage(user_id)

        readiness_data = {
            'api_keys': key_status,
            'permissions': permissions,
            'limits': limits,
            'usage': usage_stats,
            'reservations': {
                'live_minutes': LIVE_MINUTES_RESERVATION,
            },
        }
        logging.debug(f"{log_prefix} Returning readiness data: {readiness_data}")
        logging.debug(f"User readiness data for user {user_id}: {readiness_data}")
        return jsonify(readiness_data), 200

    except Exception as e:
        logging.error(f"{log_prefix} Error getting user readiness: {e}", exc_info=True)
        return jsonify({'error': _('Failed to retrieve user readiness status.')}), 500


# --- API Key Management Endpoints ---
@user_settings_bp.route('/keys', methods=['GET'])
@login_required
@permission_required('allow_api_key_management')
def get_api_key_status():
    """
    API endpoint to return the configuration status (set/not set) of the user's API keys.
    Used by the 'Manage API Keys' modal.
    """
    user_id = current_user.id
    log_prefix = f"[API:UserKeys:{user_id}:GET]"
    logging.debug(f"{log_prefix} Request received for API key status.")
    try:
        status = user_service.get_user_api_key_status(user_id)
        logging.info(f"{log_prefix} Returning API key status: {status}")
        return jsonify(status), 200
    except Exception as e:
        logging.error(f"{log_prefix} Error getting API key status: {e}", exc_info=True)
        return jsonify({'error': _('Failed to retrieve API key status.')}), 500


@user_settings_bp.route('/public-api-key', methods=['GET'])
@login_required
def get_public_api_key_status():
    """
    Returns the status/metadata for the user's public API key (used for authenticated API access).
    """
    user_id = current_user.id
    log_prefix = f"[API:UserPublicKey:{user_id}:GET]"
    try:
        if not check_permission(current_user, 'allow_public_api_access'):
            logging.warning(f"{log_prefix} Permission denied for public API key status.")
            return jsonify({'error': _('You do not have permission to use the public API.')}), 403
        status = user_service.get_public_api_key_status(user_id)
        logging.info(f"{log_prefix} Returning public API key status.")
        return jsonify(status), 200
    except UserNotFoundError as e:
        logging.warning(f"{log_prefix} User not found: {e}")
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logging.error(f"{log_prefix} Error getting public API key status: {e}", exc_info=True)
        return jsonify({'error': _('Failed to retrieve API key status.')}), 500


@user_settings_bp.route('/public-api-key', methods=['POST'])
@login_required
def generate_public_api_key():
    """
    Generates (or regenerates) a public API key for the authenticated user.
    Returns the plaintext key once so it can be copied.
    """
    user_id = current_user.id
    log_prefix = f"[API:UserPublicKey:{user_id}:POST]"
    try:
        if not check_permission(current_user, 'allow_public_api_access'):
            logging.warning(f"{log_prefix} Permission denied for public API key generation.")
            return jsonify({'error': _('You do not have permission to use the public API.')}), 403
        name = (request.form.get('name') or (request.get_json(silent=True) or {}).get('name') or '').strip()
        key_data = user_service.generate_public_api_key(user_id, name=name)
        logging.info(f"{log_prefix} Public API key generated.")
        return jsonify(key_data), 201
    except UserNotFoundError as e:
        logging.warning(f"{log_prefix} User not found: {e}")
        return jsonify({'error': str(e)}), 404
    except (ValueError, ApiKeyManagementError) as e:
        logging.error(f"{log_prefix} Failed to generate public API key: {e}")
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error generating public API key: {e}", exc_info=True)
        return jsonify({'error': _('An unexpected error occurred while generating the API key.')}), 500


@user_settings_bp.route('/public-api-key', methods=['DELETE'])
@login_required
def delete_public_api_key():
    """
    Revokes the stored public API key for the authenticated user.
    """
    user_id = current_user.id
    log_prefix = f"[API:UserPublicKey:{user_id}:DELETE]"
    try:
        if not check_permission(current_user, 'allow_public_api_access'):
            logging.warning(f"{log_prefix} Permission denied for public API key revoke.")
            return jsonify({'error': _('You do not have permission to use the public API.')}), 403
        user_service.revoke_public_api_key(user_id)
        logging.info(f"{log_prefix} Public API key revoked.")
        return jsonify({'message': _('Public API key revoked.')}), 200
    except UserNotFoundError as e:
        logging.warning(f"{log_prefix} User not found: {e}")
        return jsonify({'error': str(e)}), 404
    except ApiKeyManagementError as e:
        logging.error(f"{log_prefix} Failed to revoke public API key: {e}")
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error revoking public API key: {e}", exc_info=True)
        return jsonify({'error': _('An unexpected error occurred while revoking the API key.')}), 500


@user_settings_bp.route('/public-api-key/<int:key_id>', methods=['DELETE'])
@login_required
def delete_named_public_api_key(key_id):
    """
    Revokes one stored public API key for the authenticated user.
    """
    user_id = current_user.id
    log_prefix = f"[API:UserPublicKey:{user_id}:DELETE:{key_id}]"
    try:
        if not check_permission(current_user, 'allow_public_api_access'):
            logging.warning(f"{log_prefix} Permission denied for public API key revoke.")
            return jsonify({'error': _('You do not have permission to use the public API.')}), 403
        user_service.revoke_public_api_key(user_id, key_id=key_id)
        logging.info(f"{log_prefix} Public API key revoked.")
        return jsonify({'message': _('Public API key revoked.')}), 200
    except KeyNotFoundError as e:
        logging.warning(f"{log_prefix} Public API key not found: {e}")
        return jsonify({'error': str(e)}), 404
    except UserNotFoundError as e:
        logging.warning(f"{log_prefix} User not found: {e}")
        return jsonify({'error': str(e)}), 404
    except ApiKeyManagementError as e:
        logging.error(f"{log_prefix} Failed to revoke public API key: {e}")
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error revoking public API key: {e}", exc_info=True)
        return jsonify({'error': _('An unexpected error occurred while revoking the API key.')}), 500

@user_settings_bp.route('/keys', methods=['POST'])
@login_required
@permission_required('allow_api_key_management')
def save_api_key():
    """
    API endpoint to save or update an API key for a specific service for the logged-in user.
    Uses WTForms (ApiKeyForm) for validation, including CSRF protection.
    """
    user_id = current_user.id
    log_prefix = f"[API:UserKeys:{user_id}:POST]"
    if request.is_json:
        form = ApiKeyForm(meta={'csrf': False}, data=request.get_json(silent=True) or {})
        form_valid = form.validate()
    else:
        form = ApiKeyForm()
        form_valid = form.validate_on_submit()

    if form_valid:
        service = form.service.data
        api_key = form.api_key.data
        logging.info(f"{log_prefix} Attempting to save API key for service '{service}'.")
        # The modal sends one model_purpose value per checked box; JSON clients
        # send a single value. Each purpose is saved in turn and the key row
        # accumulates them.
        raw_purposes = [] if request.is_json else request.form.getlist('model_purpose')
        purposes = list(dict.fromkeys(p for p in raw_purposes if p)) or [
            form.model_purpose.data or form.openrouter_model_purpose.data
        ]
        if any(p not in ('transcription', 'llm', 'live') for p in purposes):
            return jsonify({'error': _('Please choose a valid model purpose.')}), 400
        try:
            for purpose in purposes:
                user_service.save_user_api_key(
                    user_id,
                    service,
                    api_key,
                    model_name=form.model_name.data or form.openrouter_model.data,
                    model_purpose=purpose,
                )
            logging.info(f"{log_prefix} API key for service '{service}' saved successfully.")
            return jsonify({'message': _('API key for %(service)s saved successfully.', service=service)}), 200
        except (UserNotFoundError, ValueError, DatabaseUpdateError, ApiKeyManagementError) as e:
             logging.error(f"{log_prefix} Failed to save API key for service '{service}': {e}")
             status_code = 404 if isinstance(e, UserNotFoundError) else 400 if isinstance(e, ValueError) else 500
             return jsonify({'error': str(e)}), status_code
        except Exception as e:
             logging.error(f"{log_prefix} Unexpected error saving API key for '{service}': {e}", exc_info=True)
             return jsonify({'error': _('An unexpected error occurred while saving the API key.')}), 500
    else:
        errors = form.errors
        logging.warning(f"{log_prefix} API key save failed validation: {errors}")
        return jsonify({'error': _('Validation failed'), 'errors': errors}), 400

@user_settings_bp.route('/keys/<service>', methods=['DELETE'])
@login_required
@permission_required('allow_api_key_management')
def delete_api_key(service):
    """
    API endpoint to delete a specific API key for the logged-in user.
    Handles 'openai', 'assemblyai', and 'gemini'.
    """
    user_id = current_user.id
    log_prefix = f"[API:UserKeys:{user_id}:DELETE:{service}]"

    allowed_services = ['openai', 'assemblyai', 'gemini', 'openrouter']
    if service not in allowed_services:
        logging.warning(f"{log_prefix} Attempt to delete key for invalid service in URL: {service}")
        return jsonify({'error': _('Invalid service specified in URL.')}), 400

    logging.info(f"{log_prefix} Attempting to delete API key.")
    try:
        key_id = request.args.get('key_id', type=int)
        if key_id is not None:
            user_service.delete_user_api_key_by_id(user_id, key_id)
        else:
            model_slug = request.args.get('model')
            user_service.delete_user_api_key(user_id, service, model_slug=model_slug)
        logging.info(f"{log_prefix} API key deleted successfully.")
        return jsonify({'message': _('API key for %(service)s deleted successfully.', service=service)}), 200
    except KeyNotFoundError as e:
        logging.warning(f"{log_prefix} Failed to delete API key: {e}")
        return jsonify({'error': str(e)}), 404 
    except (UserNotFoundError, DatabaseUpdateError, ValueError, ApiKeyManagementError) as e:
        logging.error(f"{log_prefix} Failed to delete API key: {e}")
        status_code = 404 if isinstance(e, UserNotFoundError) else 400 if isinstance(e, ValueError) else 500
        return jsonify({'error': str(e)}), status_code
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error deleting API key: {e}", exc_info=True)
        return jsonify({'error': _('An unexpected error occurred while deleting the API key.')}), 500


# --- User Profile Endpoints ---

@user_settings_bp.route('/model-catalog', methods=['GET'])
@login_required
def get_model_catalog():
    """
    API endpoint returning the model catalogs for dropdown consumers, rebuilt
    from the caller's current key status. Lets pages opened before a key was
    saved (Manage API Keys) refresh their window globals without a reload.
    Mirrors inject_global_vars so a fresh page render cannot disagree with it.
    """
    user_obj: User = current_user
    log_prefix = f"[API:UserModelCatalog:{user_obj.id}:GET]"
    try:
        is_multi = access_service.is_team_mode()
        # Personal mode merges the .env provider keys into this status.
        initial_key_status = user_service.get_effective_key_status(user_obj)

        from app.models import transcription_catalog as transcription_catalog_model
        from app.models import llm_catalog as llm_catalog_model

        catalog_models = transcription_catalog_model.get_active_models()
        available_transcription_models = transcription_catalog_model.build_model_options(
            catalog_models,
            initial_key_status,
        )

        live_transcription_models = transcription_catalog_model.get_live_models(initial_key_status)

        llm_model_catalog = llm_catalog_model.get_active_models()
        effective_key_status = dict(initial_key_status)
        for service in ('openai', 'assemblyai', 'gemini', 'openrouter'):
            effective_key_status[service] = bool(
                effective_key_status.get(service)
                or current_app.config.get(f'{service.upper()}_API_KEY')
            )
        llm_model_catalog = llm_catalog_model.filter_models_by_api_key_status(
            llm_model_catalog,
            effective_key_status,
            allow_provider_wide=not is_multi,
        )

        return jsonify({
            'transcription': available_transcription_models,
            'live': live_transcription_models,
            'llm': llm_model_catalog,
        }), 200
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error building model catalog: {e}", exc_info=True)
        return jsonify({'error': _('An unexpected error occurred while loading the model catalog.')}), 500


@user_settings_bp.route('/profile', methods=['GET'])
@login_required
def get_profile():
    """API endpoint to get the current user's profile data."""
    user_obj: User = current_user 
    log_prefix = f"[API:UserProfile:{user_obj.id}:GET]"
    logging.debug(f"{log_prefix} Request received.")
    try:
        profile_data = {
            'username': user_obj.username,
            'email': user_obj.email,
            'first_name': user_obj.first_name,
            'last_name': user_obj.last_name,
            'default_content_language': user_obj.default_content_language,
            'default_transcription_model': user_obj.default_transcription_model,
            'default_title_generation_model': getattr(user_obj, 'default_title_generation_model', None),
            'default_workflow_model': getattr(user_obj, 'default_workflow_model', None),
            'default_live_transcription_model': getattr(user_obj, 'default_live_transcription_model', None),
            'oauth_provider': user_obj.oauth_provider,
            'enable_auto_title_generation': user_obj.enable_auto_title_generation,
            'language': user_obj.language
        }
        return jsonify(profile_data), 200
    except Exception as e:
        logging.error(f"{log_prefix} Error retrieving profile data: {e}", exc_info=True)
        return jsonify({'error': _('Failed to retrieve profile data.')}), 500


@user_settings_bp.route('/profile', methods=['PUT'])
@login_required
def update_profile():
    """API endpoint to update the user's profile information and preferences."""
    user_id = current_user.id
    log_prefix = f"[API:UserProfile:{user_id}:PUT]"
    form_data = request.get_json() 

    logging.debug(f"{log_prefix} Received profile update data: {form_data}")
    form = UserProfileForm(data=form_data)
    logging.debug(
        f"{log_prefix} Form data after instantiation: Lang='{form.default_content_language.data}', "
        f"Model='{form.default_transcription_model.data}', "
        f"AuxiliaryModel='{form.default_title_generation_model.data}', "
        f"WorkflowModel='{form.default_workflow_model.data}', "
        f"AutoTitle='{form.enable_auto_title_generation.data}'"
    )

    if form.validate():
        logging.info(f"{log_prefix} Profile update request validated.")
        try:
            validated_profile_data = dict(form.data)
            # Preserve older API clients: an omitted new preference should not
            # clear a value that was previously saved for the user.
            for preference_field in (
                'default_title_generation_model',
                'default_workflow_model',
                'default_live_transcription_model',
            ):
                if preference_field not in (form_data or {}):
                    validated_profile_data.pop(preference_field, None)
            user_service.update_profile(user_id, validated_profile_data)
            logging.info(f"{log_prefix} Profile updated successfully.")
            return jsonify({'message': _('Profile updated successfully.')}), 200
        except UsernameTakenError as e:
            logging.warning(f"{log_prefix} Profile update failed: {e}")
            return jsonify({'error': str(e), 'field': 'username'}), 409
        except EmailTakenError as e:
            logging.warning(f"{log_prefix} Profile update failed: {e}")
            return jsonify({'error': str(e), 'field': 'email'}), 409
        except (UserNotFoundError, ProfileUpdateError, DatabaseUpdateError) as e:
            logging.error(f"{log_prefix} Profile update failed: {e}")
            status_code = 404 if isinstance(e, UserNotFoundError) else 500
            return jsonify({'error': str(e)}), status_code
        except Exception as e:
            logging.error(f"{log_prefix} Unexpected error updating profile: {e}", exc_info=True)
            return jsonify({'error': _('An unexpected error occurred while updating the profile.')}), 500
    else:
        errors = form.errors
        logging.warning(f"{log_prefix} Profile update failed validation: {errors}")
        return jsonify({'error': _('Validation failed'), 'errors': errors}), 400


@user_settings_bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    """API endpoint for the user to change their own password."""
    user_id = current_user.id
    log_prefix = f"[API:UserPassword:{user_id}:POST]"
    form = ChangePasswordForm(data=request.get_json())

    if current_user.oauth_provider and not current_user.password_hash:
         logging.warning(f"{log_prefix} Password change attempt failed: User logged in via OAuth and has no password set.")
         return jsonify({'error': _('Password change is not available for accounts signed in via Google/OAuth.')}), 400

    if form.validate():
        logging.info(f"{log_prefix} Change password request validated.")
        try:
            auth_service.change_password(
                user_id,
                form.current_password.data,
                form.new_password.data
            )
            logging.info(f"{log_prefix} Password changed successfully.")
            return jsonify({'message': _('Password changed successfully.')}), 200
        except InvalidCredentialsError as e:
            logging.warning(f"{log_prefix} Password change failed: {e}")
            return jsonify({'error': str(e), 'field': 'current_password'}), 400
        except (ValueError, AuthServiceError) as e:
            logging.error(f"{log_prefix} Password change failed: {e}")
            status_code = 400 if isinstance(e, ValueError) else 500
            return jsonify({'error': str(e)}), status_code
        except Exception as e:
            logging.error(f"{log_prefix} Unexpected error changing password: {e}", exc_info=True)
            return jsonify({'error': _('An unexpected error occurred while changing the password.')}), 500
    else:
        errors = form.errors
        logging.warning(f"{log_prefix} Change password failed validation: {errors}")
        return jsonify({'error': _('Validation failed'), 'errors': errors}), 400


# --- User Prompt Management Endpoints ---
@user_settings_bp.route('/prompts', methods=['GET']) 
@login_required
def get_user_prompts_api():
    """
    API endpoint to get user's saved prompts.
    Now returns a single list of all prompts for the user.
    """
    user_id = current_user.id
    log_prefix = f"[API:UserPrompts:{user_id}:GET]"
    try:
        user_prompts: List[UserPrompt] = user_service.get_user_prompts(user_id)
        
        # --- MODIFIED: Include source_template_id in the response ---
        prompt_dicts = [
            {
                'id': p.id,
                'title': p.title,
                'prompt_text': p.prompt_text,
                'color': p.color,
                'source_template_id': p.source_template_id
            } for p in user_prompts
        ]

        return jsonify(prompt_dicts), 200
        # --- END MODIFIED ---
    except Exception as e:
        logging.error(f"{log_prefix} Error fetching user prompts: {e}", exc_info=True)
        return jsonify({'error': _('Failed to retrieve user prompts.')}), 500

@user_settings_bp.route('/prompts', methods=['POST']) 
@login_required
def save_user_prompt_api():
    """API endpoint to save a new custom prompt."""
    user_id = current_user.id
    log_prefix = f"[API:UserPrompts:{user_id}:POST]"
    data = request.get_json()
    logging.debug(f"{log_prefix} Received raw data: {data}")
    if not data or not data.get('title') or not data.get('prompt_text'):
        return jsonify({'error': _('Missing title or prompt_text in request body.')}), 400

    title = data['title']
    prompt_text = data['prompt_text']
    color = data.get('color', '#ffffff') 
    logging.debug(f"{log_prefix} Extracted color: '{color}' (Type: {type(color)})")

    try:
        new_prompt = user_service.save_user_prompt(user_id, title, prompt_text, color)
        if new_prompt:
            return jsonify({
                'message': _('Prompt saved successfully.'),
                'prompt': {'id': new_prompt.id, 'title': new_prompt.title, 'prompt_text': new_prompt.prompt_text, 'color': new_prompt.color, 'source_template_id': new_prompt.source_template_id}
            }), 201
        else:
            raise PromptManagementError(_("Failed to save prompt (service returned None)."))
    except DuplicatePromptError as e:
        logging.warning(f"{log_prefix} Failed to save prompt: {e}")
        return jsonify({'error': str(e)}), 409
    except DataLengthError as e:
        logging.warning(f"{log_prefix} Failed to save prompt due to invalid data length: {e}")
        return jsonify({'error': str(e)}), 400
    except PromptManagementError as e:
        logging.error(f"{log_prefix} Error saving prompt: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error saving prompt: {e}", exc_info=True)
        return jsonify({'error': _('An unexpected error occurred while saving the prompt.')}), 500

@user_settings_bp.route('/prompts/<int:prompt_id>', methods=['PUT']) 
@login_required
def update_user_prompt_api(prompt_id: int):
    """API endpoint to update an existing custom prompt."""
    user_id = current_user.id
    log_prefix = f"[API:UserPrompts:{user_id}:PUT:{prompt_id}]"
    data = request.get_json()
    logging.debug(f"{log_prefix} Received raw data for update: {data}")
    if not data or not data.get('title') or not data.get('prompt_text'):
        return jsonify({'error': _('Missing title or prompt_text in request body.')}), 400

    title = data['title']
    prompt_text = data['prompt_text']
    color = data.get('color', '#ffffff') 
    logging.debug(f"{log_prefix} Extracted color for update: '{color}' (Type: {type(color)})")

    try:
        success = user_service.update_user_prompt(prompt_id, user_id, title, prompt_text, color)
        if success:
            return jsonify({'message': _('Prompt updated successfully.')}), 200
        else:
            return jsonify({'error': _('Failed to update prompt (check ownership or logs).')}), 500
    except PromptNotFoundError as e:
        logging.warning(f"{log_prefix} Update failed: {e}")
        return jsonify({'error': str(e)}), 404
    except PromptManagementError as e: 
        logging.error(f"{log_prefix} Error updating prompt: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error updating prompt: {e}", exc_info=True)
        return jsonify({'error': _('An unexpected error occurred while updating the prompt.')}), 500

@user_settings_bp.route('/prompts/<int:prompt_id>', methods=['DELETE']) 
@login_required
def delete_user_prompt_api(prompt_id: int):
    """API endpoint to delete a custom prompt."""
    user_id = current_user.id
    log_prefix = f"[API:UserPrompts:{user_id}:DELETE:{prompt_id}]"
    try:
        success = user_service.delete_user_prompt(prompt_id, user_id)
        if success:
            return jsonify({'message': _('Prompt deleted successfully.')}), 200
        else:
            return jsonify({'error': _('Failed to delete prompt (check ownership or logs).')}), 500
    except PromptNotFoundError as e:
        logging.warning(f"{log_prefix} Delete failed: {e}")
        return jsonify({'error': str(e)}), 404
    except PromptManagementError as e: 
        logging.error(f"{log_prefix} Error deleting prompt: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error deleting prompt: {e}", exc_info=True)
        return jsonify({'error': _('An unexpected error occurred while deleting the prompt.')}), 500
