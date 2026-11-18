# app/services/user_service.py
# Handles user-specific business logic, particularly API key management and profile updates.

from app.logging_config import get_logger
import re # For Gemini API key validation
import secrets
import hmac
import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List 

from cryptography.fernet import InvalidToken
from flask import current_app

# Import model and User class
from app.models import user as user_model 
from app.models import user_api_key as user_api_key_model
from app.models import public_api_key as public_api_key_model
from app.models import user_prompt as user_prompt_model
from app.models import template_prompt as template_prompt_model
from app.models.user import User 
from app.models.user_prompt import UserPrompt
from app.models.template_prompt import TemplatePrompt
from app.models import transcription as transcription_model
from app.services.openrouter import normalize_openrouter_model

# Import security service for encryption/decryption
from .security_service import get_security_service, SecurityService

# Import MySQL error class for potential specific checks if needed
from mysql.connector import Error as MySQLError

from app.database import get_cursor


# --- Custom Exceptions ---
class UserNotFoundError(Exception):
    """User not found in the database."""
    pass

class ApiKeyManagementError(Exception):
    """General error during API key management."""
    pass

class MissingApiKeyError(ApiKeyManagementError):
    """Required API key is missing or not configured for the user."""
    pass

class ApiKeyDecryptionError(MissingApiKeyError):
    """A stored API key exists but could not be decrypted.

    Raised instead of returning None so callers do not mistake a broken key
    (corrupted ciphertext or rotated SECRET_KEY) for a missing one and
    silently fall back to another credential.
    """
    pass

class KeyNotFoundError(ApiKeyManagementError):
    """API key for a specific service not found for the user."""
    pass

class DatabaseUpdateError(ApiKeyManagementError):
    """Failed to update the database during key management."""
    pass

class ProfileUpdateError(Exception):
    """General error during profile update."""
    pass

class UsernameTakenError(ProfileUpdateError):
    """Username is already taken by another user."""
    pass

class EmailTakenError(ProfileUpdateError):
    """Email is already taken by another user."""
    pass

class PromptManagementError(Exception):
    """General error during prompt management."""
    pass

class PromptNotFoundError(PromptManagementError):
    """Prompt not found."""
    pass

class DuplicatePromptError(PromptManagementError):
    """A prompt with the same title already exists for the user."""
    pass

class DataLengthError(PromptManagementError):
    """Input data exceeds the maximum allowed length for a database field."""
    pass


# --- API Key Management ---

def _hash_public_api_key(raw_key: str) -> str:
    """
    Creates an HMAC-SHA256 hash of the raw API key using the app SECRET_KEY.
    """
    secret = current_app.config.get('SECRET_KEY')
    if not secret:
        raise ValueError("SECRET_KEY is required to generate public API keys.")
    return hmac.new(secret.encode('utf-8'), raw_key.encode('utf-8'), hashlib.sha256).hexdigest()

def _normalize_model_name(service: str, model_name: Optional[str], *, required: bool = False) -> Optional[str]:
    """Normalize a provider-local model name while preserving legacy blanks."""
    value = str(model_name or '').strip()
    if not value:
        if required:
            raise ValueError("Model name is required.")
        return None
    if len(value) > 120 or any(char.isspace() for char in value):
        raise ValueError("Model name must be 120 characters or fewer and contain no spaces.")
    if service == 'openrouter':
        return normalize_openrouter_model(value)
    if '/' in value:
        raise ValueError("Model name for this provider must not include '/'.")
    return value


def save_user_api_key(
    user_id: int,
    service: str,
    api_key: str,
    model_name: Optional[str] = None,
    model_purpose: str = 'transcription',
    *,
    # Backward-compatible keyword names used by older callers/tests.
    openrouter_model: Optional[str] = None,
    openrouter_model_purpose: Optional[str] = None,
) -> bool:
    """Encrypt and save a provider/model-scoped API key.

    A blank model name is accepted only for legacy provider-wide API clients;
    AssemblyAI's legacy blank transcription key is normalized to its
    provider-local ``universal`` model. OpenRouter retains its vendor/model
    validation rules, while other providers use a provider-local model name.
    A masked saved-key value is resolved across the provider's existing keys
    only while saving, then stored under the requested model's own row.
    """
    logger = get_logger(__name__, user_id=user_id, component="UserService")
    if model_name is None:
        model_name = openrouter_model
    if openrouter_model_purpose and model_purpose == 'transcription':
        model_purpose = openrouter_model_purpose
    if not service or not api_key:
        logger.error("Attempted to save empty service or API key.")
        raise ValueError("Service name and API key cannot be empty.")

    api_key = str(api_key).strip()
    if not api_key:
        logger.error("Attempted to save an empty API key after trimming whitespace.")
        raise ValueError("Service name and API key cannot be empty.")

    allowed_services = ['openai', 'assemblyai', 'gemini', 'openrouter']
    service = service.lower()
    if service not in allowed_services:
        logger.error(f"Attempted to save API key for invalid service: {service}")
        raise ValueError(f"Invalid service specified: {service}. Must be one of {allowed_services}.")
    if model_purpose not in ('transcription', 'llm', 'live'):
        raise ValueError("Model purpose must be 'transcription', 'llm', or 'live'.")

    normalized_model_name = _normalize_model_name(
        service,
        model_name,
        required=service == 'openrouter',
    )
    if service == 'assemblyai' and model_purpose == 'transcription':
        # Older deployments stored AssemblyAI as a provider-wide key. The
        # client code's underlying default is the Universal model, so keep the
        # saved key aligned with the selectable catalog model.
        if not normalized_model_name or normalized_model_name.casefold() == 'assemblyai':
            normalized_model_name = 'universal'

    try:
        user = user_model.get_user_by_id(user_id)
        if not user:
            logger.error("User not found when trying to save API key.")
            raise UserNotFoundError(f"User with ID {user_id} not found.")

        if api_key.startswith('***'):
            existing_key = get_decrypted_api_key(
                user_id,
                service,
                normalized_model_name,
                allow_model_fallback=True,
            )
            if (
                not existing_key
                or len(api_key) != 6
                or api_key[3:] != existing_key[-3:]
            ):
                raise ValueError(
                    "Enter a complete API key or use the suggested saved key."
                )
            api_key = existing_key

        security_svc: SecurityService = get_security_service()
        encrypted_key = security_svc.encrypt_data(api_key)
        logger.debug(f"API key for service '{service}' encrypted.")

        success = user_api_key_model.upsert_api_key(
            user_id,
            service,
            encrypted_key,
            normalized_model_name,
            model_purpose=model_purpose,
        )
        if not success:
            logger.error(f"Failed to persist API key for service '{service}'.")
            raise DatabaseUpdateError("Failed to update API keys in the database.")

        # Register the model in the catalog so it becomes selectable app-wide.
        # Transcription/live keys register a transcription model row; LLM keys
        # register an LLM model row. Display name defaults to the raw model
        # name and is never overwritten on re-saves (admin renames stick).
        if normalized_model_name:
            try:
                from app.models import transcription_catalog as transcription_catalog_model
                from app.models import llm_catalog as llm_catalog_model
                if model_purpose == 'llm':
                    llm_catalog_model.register_model_from_provider(
                        provider=service,
                        code=normalized_model_name,
                        display_name=normalized_model_name,
                    )
                else:
                    if model_purpose == 'live':
                        # Registration only ever accumulates purposes, so make
                        # the row match the surviving key rows first (idempotent;
                        # narrows rows left stale by earlier delete/re-add flows).
                        transcription_catalog_model.reconcile_model_purposes(
                            service, normalized_model_name
                        )
                    transcription_catalog_model.register_model_from_provider(
                        provider=service,
                        code=normalized_model_name,
                        display_name=normalized_model_name,
                        model_purpose=model_purpose if model_purpose == 'live' else 'transcription',
                    )
            except Exception as catalog_err:
                # The key itself is saved; catalog registration is best-effort
                # so a catalog hiccup never fails the key save.
                logger.error(f"Failed to register model '{normalized_model_name}' for service '{service}': {catalog_err}", exc_info=True)

        preference_field = None
        preference_kwargs = {}
        preference_value = normalized_model_name
        if model_purpose == 'live' and normalized_model_name:
            # Live defaults use the same qualified identity as the catalog;
            # keep the provider-local model slug in the API-key row itself.
            local_model = (
                'universal'
                if service == 'assemblyai' and normalized_model_name.casefold() == 'assemblyai'
                else normalized_model_name
            )
            preference_value = f"{service}:{local_model}"
            preference_field = 'default_live_transcription_model'
            preference_kwargs = {'default_live_transcription_model': preference_value}

        if preference_kwargs:
            preference_updated = user_model.update_user_preferences(
                user_id, None, None, **preference_kwargs
            )
            if not preference_updated:
                refreshed_user = user_model.get_user_by_id(user_id)
                if (
                    preference_field
                    and (not refreshed_user or getattr(refreshed_user, preference_field, None) != preference_value)
                ):
                    raise DatabaseUpdateError("Failed to persist the model preference.")
            logger.info(
                "Saved model '%s' for service '%s' and purpose '%s'.",
                preference_value,
                service,
                model_purpose,
            )

        logger.debug(f"Successfully saved encrypted API key for service '{service}'.")
        return True

    except (UserNotFoundError, ValueError, DatabaseUpdateError) as e:
         raise e
    except MySQLError as db_err:
        logger.error(f"Database error saving API key for service '{service}': {db_err}", exc_info=True)
        raise ApiKeyManagementError(f"A database error occurred while saving the API key for {service}.") from db_err
    except Exception as e:
        logger.error(f"Unexpected error saving API key for service '{service}': {e}", exc_info=True)
        raise ApiKeyManagementError(f"An unexpected error occurred while saving the API key for {service}.") from e

def get_decrypted_api_key(
    user_id: int,
    service: str,
    model_slug: Optional[str] = None,
    *,
    allow_model_fallback: bool = False,
) -> Optional[str]:
    """
    Retrieves and decrypts a user's API key.

    Named model lookups require an exact model row. The save flow can opt into
    model fallback so a masked provider key can be reused when adding a new
    model; normal runtime lookups stay model-scoped.
    """
    logger = get_logger(__name__, user_id=user_id, component="UserService")
    if not service:
        logger.error("Attempted to get API key for empty service.")
        return None
    service = service.lower()

    normalized_model_slug = None
    if model_slug:
        try:
            normalized_model_slug = _normalize_model_name(service, model_slug, required=True)
        except ValueError as err:
            logger.warning(f"Invalid model name while fetching API key: {err}")
            return None

    try:
        user = user_model.get_user_by_id(user_id)
        if not user:
            logger.debug("User not found when fetching encrypted API keys.")
            return None

        record = user_api_key_model.get_api_key_record(
            user_id,
            service,
            normalized_model_slug,
            allow_model_fallback=allow_model_fallback,
        )
        if not record:
            logger.debug(
                f"API key for service '{service}' and model '{normalized_model_slug}' "
                "not found in stored keys."
            )
            return None

        encrypted_key = record.get("encrypted_key")
        if not encrypted_key:
            return None

        security_svc: SecurityService = get_security_service()
        try:
            decrypted_key = security_svc.decrypt_data(encrypted_key)
            key_id = record.get("id")
            if key_id is not None:
                user_api_key_model.mark_api_key_used(user_id, key_id)
            logger.debug(
                f"Successfully decrypted API key for service '{service}' "
                f"and model '{normalized_model_slug}'."
            )
            return decrypted_key
        except InvalidToken:
            logger.error(
                f"Decryption failed for service '{service}': Invalid Token. "
                "Key might be corrupted or SECRET_KEY changed."
            )
            # A stored-but-unreadable key must not look like a missing key:
            # callers would silently fall back to admin/global credentials.
            raise ApiKeyDecryptionError(
                f"Stored API key for '{service}' could not be decrypted. "
                "It may be corrupted or the application secret has changed; re-save the key."
            )
        except ValueError as ve:
            logger.error(f"Decryption error for service '{service}': {ve}", exc_info=True)
            return None

    except ApiKeyDecryptionError:
        # Propagate: a broken stored key must not fall back to other credentials.
        raise
    except MySQLError as db_err:
        logger.error(f"Database error getting API key for service '{service}': {db_err}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Unexpected error getting API key for service '{service}': {e}", exc_info=True)
        return None


def get_admin_decrypted_api_key(
    service: str,
    model_slug: Optional[str] = None,
) -> Optional[str]:
    """Return an exact model key configured by an admin, if one exists.

    Provider-wide admin keys are deliberately not used for named models here:
    the model must have its own admin-saved row before it is available to users
    who cannot manage keys. The provider-wide row remains useful for the
    provider's default/no-model path and for preloading a new model in the UI.
    """
    logger = get_logger(__name__, component="UserService")
    if not service:
        return None
    service = service.lower()

    normalized_model_slug = None
    if model_slug:
        try:
            normalized_model_slug = _normalize_model_name(service, model_slug, required=True)
        except ValueError as err:
            logger.warning("Invalid model name while fetching admin API key: %s", err)
            return None

    try:
        lookup_model_slug = normalized_model_slug if normalized_model_slug is not None else ''
        records = user_api_key_model.get_admin_api_key_records(
            service,
            model_slug=lookup_model_slug,
        )
        security_svc: SecurityService = get_security_service()
        for record in records:
            # A named model requires a named admin row. This is the runtime
            # counterpart to the exact-model UI gate. An unscoped request may
            # use only a provider-wide row.
            if str(record.get('model_slug') or '').strip() != lookup_model_slug:
                continue
            encrypted_key = record.get("encrypted_key")
            if not encrypted_key:
                continue
            try:
                decrypted_key = security_svc.decrypt_data(encrypted_key)
            except InvalidToken:
                logger.error(
                    "Admin API key for provider '%s' could not be decrypted "
                    "(corrupted or SECRET_KEY changed).",
                    service,
                )
                raise ApiKeyDecryptionError(
                    f"Stored admin API key for '{service}' could not be decrypted. "
                    "It may be corrupted or the application secret has changed; re-save the key."
                )
            except (ValueError, TypeError):
                logger.warning(
                    "Skipping an unreadable admin API key for provider '%s'.",
                    service,
                )
                continue
            if not decrypted_key:
                continue
            owner_id = record.get("user_id")
            key_id = record.get("id")
            if owner_id is not None and key_id is not None:
                user_api_key_model.mark_api_key_used(owner_id, key_id)
            return decrypted_key
    except ApiKeyDecryptionError:
        # Propagate: a broken stored key must not fall back to other credentials.
        raise
    except Exception as err:
        logger.error(
            "Error retrieving admin API key for service '%s' and model '%s': %s",
            service,
            normalized_model_slug,
            err,
            exc_info=True,
        )
    return None


def delete_user_api_key(
    user_id: int,
    service: str,
    model_slug: Optional[str] = None,
) -> None:
    """
    Deletes a user's API key. OpenRouter can target one model slug; omitting
    the slug preserves the legacy behavior of deleting all OpenRouter keys.
    """
    logger = get_logger(__name__, user_id=user_id, component="UserService")
    if not service:
        logger.error("Attempted to delete API key for empty service.")
        raise ValueError("Service name cannot be empty.")

    allowed_services = ['openai', 'assemblyai', 'gemini', 'openrouter']
    service = service.lower()
    if service not in allowed_services:
        logger.error(f"Attempted to delete API key for invalid service: {service}")
        raise ValueError(f"Invalid service specified: {service}. Must be one of {allowed_services}.")
    if model_slug is not None:
        model_slug = _normalize_model_name(service, model_slug, required=True)

    try:
        user = user_model.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User with ID {user_id} not found.")

        removed = user_api_key_model.delete_api_key(
            user_id, service, model_slug=model_slug
        )
        if not removed:
            logger.warning(f"API key for service '{service}' not found or could not be removed.")
            raise KeyNotFoundError(f"API key for service '{service}' not found.")
        if model_slug:
            # The deleted key may have been the last one granting a purpose;
            # shrink the catalog row so the model leaves unused dropdowns.
            try:
                from app.models import transcription_catalog as transcription_catalog_model
                transcription_catalog_model.reconcile_model_purposes(
                    service, model_slug
                )
            except Exception as reconcile_err:
                logger.error(
                    "Failed to reconcile catalog purposes for %s:%s after key deletion: %s",
                    service,
                    model_slug,
                    reconcile_err,
                    exc_info=True,
                )
        logger.debug(f"Successfully removed API key for service '{service}'.")

    except (UserNotFoundError, KeyNotFoundError, DatabaseUpdateError, ValueError) as specific_error:
        raise specific_error
    except MySQLError as db_err:
        logger.error(f"Database error deleting API key for service '{service}': {db_err}", exc_info=True)
        raise ApiKeyManagementError(f"A database error occurred while deleting the API key for {service}.") from db_err
    except Exception as e:
        logger.error(f"Unexpected error deleting API key for service '{service}': {e}", exc_info=True)
        raise ApiKeyManagementError(f"An unexpected error occurred while deleting the API key for {service}.") from e


def delete_user_api_key_by_id(user_id: int, key_id: int) -> None:
    """Delete one provider/model key without widening a provider-wide delete."""
    logger = get_logger(__name__, user_id=user_id, component="UserService")
    user = user_model.get_user_by_id(user_id)
    if not user:
        raise UserNotFoundError(f"User with ID {user_id} not found.")
    key_record = user_api_key_model.get_api_key_record_by_id(user_id, key_id)
    if user_api_key_model.delete_api_key_by_id(user_id, key_id):
        if key_record and str(key_record.get("model_slug") or "").strip():
            # The deleted key may have been the last one granting a purpose;
            # shrink the catalog row so the model leaves unused dropdowns.
            try:
                from app.models import transcription_catalog as transcription_catalog_model
                transcription_catalog_model.reconcile_model_purposes(
                    str(key_record.get("provider_code") or ""),
                    str(key_record.get("model_slug") or ""),
                )
            except Exception as reconcile_err:
                logger.error(
                    "Failed to reconcile catalog purposes after deleting key %s: %s",
                    key_id,
                    reconcile_err,
                    exc_info=True,
                )
        return
    raise KeyNotFoundError("API key not found.")

def _collect_key_status_entries(
    status: Dict[str, Any],
    records: List[Dict[str, Any]],
    security_svc: SecurityService,
    logger,
    user: Optional[Any] = None,
) -> None:
    """
    Fills ``status['provider_keys']`` from API key records.
    ``user`` is optional: it only supplies legacy OpenRouter default names for
    provider-wide keys, so aggregated (admin) status can reuse the same logic.
    """
    providers = ('openai', 'assemblyai', 'gemini', 'openrouter')
    provider_labels = {
        'openai': 'OpenAI',
        'assemblyai': 'AssemblyAI',
        'gemini': 'Google',
        'openrouter': 'OpenRouter',
    }
    for record in records:
        provider = str(record.get('provider_code') or '').lower()
        if provider not in providers:
            continue
        encrypted_key = record.get('encrypted_key')
        if not isinstance(encrypted_key, str) or not encrypted_key:
            continue
        try:
            decrypted_key = security_svc.decrypt_data(encrypted_key)
        except (InvalidToken, ValueError, TypeError):
            logger.warning("Skipping an unreadable API key status entry for provider '%s'.", provider)
            continue
        if not decrypted_key:
            continue

        model_name = str(record.get('model_slug') or '').strip()
        raw_purposes = str(record.get('model_purposes') or '').strip()
        purposes = [
            purpose
            for purpose in raw_purposes.split(',')
            if purpose in {'transcription', 'llm', 'live'}
        ]
        if not purposes:
            purposes = ['transcription']
        if not model_name:
            model_names = [provider_labels[provider]]
        else:
            model_names = [model_name]

        for model_name in model_names:
            entry = {
                'key_id': record.get('id'),
                'model_name': model_name,
                'provider_wide': not bool(record.get('model_slug')),
                'last_three': decrypted_key[-3:],
                'model_purposes': purposes,
            }
            if provider == 'openrouter':
                if record.get('model_slug'):
                    entry['model_slug'] = model_name
            # Dedupe on the full identity (name + provider-wide flag +
            # purposes), matching _merge_key_status. Deduping by name alone
            # would drop purpose-distinct entries when several users saved
            # the same model for different purposes.
            identity = (
                model_name,
                entry['provider_wide'],
                tuple(purposes),
            )
            existing_identities = {
                (
                    str(item.get('model_name') or item.get('model_slug') or '').strip(),
                    bool(item.get('provider_wide')),
                    tuple(item.get('model_purposes') or []),
                )
                for item in status['provider_keys'][provider]
            }
            if identity in existing_identities:
                continue
            status['provider_keys'][provider].append(entry)


def _new_empty_key_status() -> Dict[str, Any]:
    """Fresh key-status shape shared by per-user and aggregated status builders."""
    providers = ('openai', 'assemblyai', 'gemini', 'openrouter')
    status: Dict[str, Any] = {
        provider: False for provider in providers
    }
    status.update({
        'provider_keys': {provider: [] for provider in providers},
        # Compatibility alias retained for existing catalog/profile callers.
        'openrouter_keys': [],
        'live_model': None,
        'public_api': {
            'enabled': False,
            'last_four': None,
            'created_at': None,
            'keys': []
        }
    })
    return status


def _finalize_key_status(status: Dict[str, Any]) -> Dict[str, Any]:
    """Populate compatibility booleans and the OpenRouter slug alias."""
    providers = ('openai', 'assemblyai', 'gemini', 'openrouter')
    for provider in providers:
        status[provider] = bool(status['provider_keys'][provider])
    status['openrouter_keys'] = [
        {
            'model_slug': entry.get('model_slug'),
            'last_three': entry.get('last_three'),
        }
        for entry in status['provider_keys']['openrouter']
    ]
    return status


def _entry_has_purpose(entry: Dict[str, Any], purpose: str) -> bool:
    """Return whether a key-status entry is usable for a given feature."""
    raw_purposes = entry.get('model_purposes')
    if isinstance(raw_purposes, str):
        raw_purposes = raw_purposes.split(',')
    purposes = {
        str(value).strip().lower()
        for value in (raw_purposes or [])
        if str(value).strip()
    }
    # Entries from before purpose metadata existed are transcription keys.
    return purpose in purposes or (not purposes and purpose == 'transcription')


def get_user_api_key_status(user_id: int) -> Dict[str, Any]:
    """Return configured provider/model key metadata without plaintext keys."""
    logger = get_logger(__name__, user_id=user_id, component="UserService")
    status = _new_empty_key_status()
    try:
        user = user_model.get_user_by_id(user_id)
        if not user:
            return status
        allow_public = False
        try:
            allow_public = bool(user.role.allow_public_api_access) if user.role else False
        except Exception:
            allow_public = False

        security_svc: SecurityService = get_security_service()
        records = user_api_key_model.get_api_key_records_by_user(user_id)
        _collect_key_status_entries(status, records, security_svc, logger, user)

        _finalize_key_status(status)
        status['live_model'] = getattr(user, 'default_live_transcription_model', None)
        status['public_api'] = get_public_api_key_status(user_id) if allow_public else status['public_api']

        logger.debug(f"API Key status checked: {status}")

    except MySQLError as db_err:
        logger.error(f"Database error checking API key status: {db_err}", exc_info=True)
    except Exception as e:
        logger.error(f"Error checking API key status: {e}", exc_info=True)
    return status


def get_aggregate_api_key_status() -> Dict[str, Any]:
    """Return key status aggregated across every user's API keys.

    Used for admin-facing model dropdowns so administrators see every model
    added by every user, not just their own keyring.
    """
    logger = get_logger(__name__, component="UserService")
    status = _new_empty_key_status()
    try:
        security_svc: SecurityService = get_security_service()
        records = user_api_key_model.get_all_api_key_records()
        _collect_key_status_entries(status, records, security_svc, logger)

        _finalize_key_status(status)
        logger.debug(f"Aggregated API key status checked: {status}")
    except Exception as e:
        logger.error(f"Error checking aggregated API key status: {e}", exc_info=True)
    return status


def get_admin_api_key_status() -> Dict[str, Any]:
    """Return model/key metadata configured by admin-panel users only."""
    logger = get_logger(__name__, component="UserService")
    status = _new_empty_key_status()
    try:
        security_svc: SecurityService = get_security_service()
        records = user_api_key_model.get_admin_api_key_records()
        _collect_key_status_entries(status, records, security_svc, logger)
        _finalize_key_status(status)
        logger.debug("Admin-configured API key status checked: %s", status)
    except Exception as err:
        logger.error("Error checking admin-configured API key status: %s", err, exc_info=True)
    return status


def _merge_key_status(*statuses: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge admin and user status without losing model-level entries."""
    merged: Dict[str, Any] = {}
    provider_names = ('openai', 'assemblyai', 'gemini', 'openrouter')
    for status in statuses:
        if not status:
            continue
        for key, value in status.items():
            if key == 'provider_keys':
                target = merged.setdefault('provider_keys', {})
                for provider, entries in (value or {}).items():
                    destination = target.setdefault(provider, [])
                    identities = {
                        (
                            str(entry.get('model_name') or entry.get('model_slug') or '').strip(),
                            bool(entry.get('provider_wide')),
                            tuple(entry.get('model_purposes') or []),
                        )
                        for entry in destination
                        if isinstance(entry, dict)
                    }
                    for entry in entries or []:
                        if not isinstance(entry, dict):
                            continue
                        identity = (
                            str(entry.get('model_name') or entry.get('model_slug') or '').strip(),
                            bool(entry.get('provider_wide')),
                            tuple(entry.get('model_purposes') or []),
                        )
                        if identity not in identities:
                            destination.append(entry)
                            identities.add(identity)
            elif key == 'openrouter_keys':
                destination = merged.setdefault('openrouter_keys', [])
                identities = {
                    str(entry.get('model_slug') or '').strip()
                    for entry in destination
                    if isinstance(entry, dict)
                }
                for entry in value or []:
                    if not isinstance(entry, dict):
                        continue
                    identity = str(entry.get('model_slug') or '').strip()
                    if identity and identity not in identities:
                        destination.append(entry)
                        identities.add(identity)
            elif key in provider_names:
                merged[key] = bool(merged.get(key)) or bool(value)
            elif key == 'public_api':
                if value and (not merged.get(key) or value.get('enabled')):
                    merged[key] = value
            elif key == 'live_model':
                if value and not merged.get(key):
                    merged[key] = value
            elif key not in merged:
                merged[key] = value

    if 'provider_keys' in merged:
        for provider in provider_names:
            merged.setdefault('provider_keys', {}).setdefault(provider, [])
            merged[provider] = bool(merged.get(provider)) or bool(merged['provider_keys'][provider])
        if not merged.get('openrouter_keys'):
            merged['openrouter_keys'] = [
                {
                    'model_slug': entry.get('model_slug'),
                    'last_three': entry.get('last_three'),
                }
                for entry in merged['provider_keys']['openrouter']
            ]
    return merged


def get_effective_key_status(user: Optional[Any]) -> Dict[str, Any]:
    """Return the key status that drives model dropdowns for ``user``.

    Admins (roles with ``access_admin_panel``) see every model added by every
    user. Other users see their own keys plus exact models configured by an
    admin, so users without key-management permission can use shared models.
    """
    if not user:
        return {}
    from app.services import access_service
    if access_service.is_personal_mode():
        # Personal mode: the owner's own keys plus provider keys from .env.
        user_id = getattr(user, 'id', None)
        own_status = get_user_api_key_status(user_id) if user_id is not None else {}
        return access_service.merge_env_provider_keys(own_status)
    role = getattr(user, 'role', None)
    if role and getattr(role, 'access_admin_panel', False):
        return get_aggregate_api_key_status()
    user_id = getattr(user, 'id', None)
    if user_id is None:
        return {}
    return _merge_key_status(
        get_admin_api_key_status(),
        get_user_api_key_status(user_id),
    )

def get_public_api_key_status(user_id: int) -> Dict[str, Optional[str]]:
    """
    Returns metadata about the user's public API key used for authenticated API access.
    """
    logger = get_logger(__name__, user_id=user_id, component="UserService")
    try:
        user = user_model.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User with ID {user_id} not found.")
        if not (user.role and user.role.has_permission('allow_public_api_access')):
            raise ApiKeyManagementError("Public API access is not permitted for this user.")

        keys = []
        for key in public_api_key_model.get_public_api_keys_by_user(user_id):
            created_at_raw = key.get('created_at')
            if isinstance(created_at_raw, datetime):
                created_at = created_at_raw.replace(tzinfo=timezone.utc).isoformat()
            else:
                created_at = str(created_at_raw) if created_at_raw else None
            keys.append({
                'id': key.get('id'),
                'name': key.get('name'),
                'last_four': key.get('last_four'),
                'created_at': created_at
            })

        legacy_created_raw = getattr(user, 'public_api_key_created_at', None)
        legacy_created = None
        if legacy_created_raw:
            if isinstance(legacy_created_raw, datetime):
                legacy_created = legacy_created_raw.replace(tzinfo=timezone.utc).isoformat()
            else:
                legacy_created = str(legacy_created_raw)

        status = {
            'enabled': bool(keys) or bool(getattr(user, 'public_api_key_hash', None)),
            'last_four': keys[0]['last_four'] if keys else getattr(user, 'public_api_key_last_four', None),
            'created_at': keys[0]['created_at'] if keys else legacy_created,
            'keys': keys
        }
        logger.debug(f"Public API key status for user {user_id}: {status}")
        return status
    except UserNotFoundError:
        raise
    except Exception as e:
        logger.error(f"Error retrieving public API key status for user {user_id}: {e}", exc_info=True)
        raise ApiKeyManagementError("Failed to retrieve public API key status.") from e


def generate_public_api_key(user_id: int, name: Optional[str] = None) -> Dict[str, str]:
    """
    Generates a new public API key for the user, storing only a hashed version.
    Returns the plaintext key once so the caller can display it.
    """
    logger = get_logger(__name__, user_id=user_id, component="UserService")
    try:
        user = user_model.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User with ID {user_id} not found.")
        if not (user.role and user.role.has_permission('allow_public_api_access')):
            raise ApiKeyManagementError("Public API access is not permitted for this user.")

        raw_key = f"tk_{secrets.token_urlsafe(32)}"
        key_hash = _hash_public_api_key(raw_key)
        last_four = raw_key[-4:]
        created_at = datetime.now(timezone.utc)
        key_name = (name or "").strip() or "Public API key"
        if len(key_name) > 120:
            raise ValueError("Key name must be 120 characters or fewer.")

        key_id = public_api_key_model.create_public_api_key(user_id, key_name, key_hash, last_four, created_at)
        if not key_id:
            raise ApiKeyManagementError("Failed to persist public API key.")

        logger.info(f"Generated new public API key for user {user_id}.")
        return {
            'id': key_id,
            'name': key_name,
            'api_key': raw_key,
            'last_four': last_four,
            'created_at': created_at.isoformat()
        }
    except (UserNotFoundError, ValueError, ApiKeyManagementError) as e:
        raise e
    except Exception as e:
        logger.error(f"Unexpected error generating public API key for user {user_id}: {e}", exc_info=True)
        raise ApiKeyManagementError("An unexpected error occurred while generating the public API key.") from e


def revoke_public_api_key(user_id: int, key_id: Optional[int] = None) -> None:
    """
    Removes the stored public API key hash/metadata for the user.
    """
    logger = get_logger(__name__, user_id=user_id, component="UserService")
    try:
        user = user_model.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User with ID {user_id} not found.")
        if not (user.role and user.role.has_permission('allow_public_api_access')):
            raise ApiKeyManagementError("Public API access is not permitted for this user.")
        if key_id is not None:
            if not public_api_key_model.revoke_public_api_key(user_id, key_id):
                raise KeyNotFoundError("Public API key not found.")
            logger.info(f"Revoked public API key {key_id} for user {user_id}.")
            return

        if not public_api_key_model.revoke_all_public_api_keys(user_id):
            raise ApiKeyManagementError("Failed to revoke the public API key.")
        logger.info(f"Revoked public API key for user {user_id}.")
    except (UserNotFoundError, KeyNotFoundError, ApiKeyManagementError) as e:
        raise e
    except Exception as e:
        logger.error(f"Unexpected error revoking public API key for user {user_id}: {e}", exc_info=True)
        raise ApiKeyManagementError("An unexpected error occurred while revoking the public API key.") from e


def authenticate_public_api_key(raw_key: str) -> Optional[User]:
    """
    Validates a presented public API key and returns the associated user if valid.
    """
    logger = get_logger(__name__, component="UserService")
    if not raw_key:
        return None
    try:
        key_hash = _hash_public_api_key(raw_key)
        user = public_api_key_model.get_user_by_public_api_key_hash(key_hash)
        if user:
            return user
        return None
    except Exception as e:
        logger.error(f"Error authenticating public API key: {e}", exc_info=True)
        return None


def hash_public_api_key_for_rate_limit(raw_key: str) -> Optional[str]:
    """
    Utility used by rate-limiters to derive a stable key from the raw API token.
    Returns None if hashing cannot be performed.
    """
    try:
        return _hash_public_api_key(raw_key)
    except Exception:
        return None


# --- Profile Update Service ---
def update_profile(user_id: int, data: Dict[str, Any]) -> None:
    """
    Updates a user's profile information and preferences.
    Performs validation, including uniqueness checks for username and email if changed.

    Args:
        user_id: The ID of the user to update.
        data: A dictionary containing the profile data, typically from a validated form.
               Expected keys: 'username', 'email', 'first_name', 'last_name',
                              'default_content_language', 'default_transcription_model',
                              'default_title_generation_model', 'default_workflow_model',
                              'default_live_transcription_model',
                              'enable_auto_title_generation', 'language'.
    """
    logger = get_logger(__name__, user_id=user_id, component="UserService")
    logger.debug(f"Attempting to update profile with data: {data}")

    required_keys = ['username', 'email']
    if not all(key in data for key in required_keys):
        raise ProfileUpdateError("Missing required profile data (username, email).")

    username = data.get('username')
    email = data.get('email')
    first_name = data.get('first_name')
    last_name = data.get('last_name')
    default_language = data.get('default_content_language')
    default_model = data.get('default_transcription_model')
    default_title_generation_model = data.get('default_title_generation_model')
    default_workflow_model = data.get('default_workflow_model')
    default_live_transcription_model = data.get('default_live_transcription_model')
    language = data.get('language')
    enable_auto_title_raw = data.get('enable_auto_title_generation')
    if isinstance(enable_auto_title_raw, bool):
        enable_auto_title = enable_auto_title_raw
    else:
        enable_auto_title = str(enable_auto_title_raw).lower() in ['true', 'on', '1', 'yes']

    from app.models import transcription_catalog as transcription_catalog_model
    default_language = None if default_language == "" else default_language
    default_model = None if default_model == "" else str(default_model or '').strip() or None
    selected_model = None
    if default_model:
        try:
            selected_model = transcription_catalog_model.get_model_by_code(default_model)
        except RuntimeError:
            # Profile-service unit callers and a few legacy import paths can
            # normalize a value before Flask has pushed an app context. Keep
            # the submitted legacy/canonical value intact; the catalog lookup
            # is retried in normal request contexts below only when needed.
            logger.debug("Could not resolve transcription model outside an app context.", exc_info=True)
        if selected_model:
            default_model = selected_model.get('model_key') or default_model
    if isinstance(default_title_generation_model, str):
        default_title_generation_model = default_title_generation_model.strip() or None
    if isinstance(default_workflow_model, str):
        default_workflow_model = default_workflow_model.strip() or None
    live_model_present = 'default_live_transcription_model' in data
    if isinstance(default_live_transcription_model, str):
        default_live_transcription_model = default_live_transcription_model.strip() or None
    if live_model_present:
        allowed_live_models = {
            str(model).strip()
            for model in current_app.config.get('LIVE_TRANSCRIPTION_MODELS', [])
            if str(model).strip()
        }
        try:
            for model in transcription_catalog_model.get_live_models():
                for candidate in (model.get('model_key'), model.get('code')):
                    candidate = str(candidate or '').strip()
                    if candidate:
                        allowed_live_models.add(candidate)
        except RuntimeError:
            logger.debug("Could not load catalog Live models while updating a profile.", exc_info=True)
        _, local_live_model = transcription_catalog_model.split_model_reference(
            default_live_transcription_model
        )
        if (
            default_live_transcription_model
            and default_live_transcription_model not in allowed_live_models
            and local_live_model not in allowed_live_models
        ):
            raise ProfileUpdateError("The selected Live transcription model is not available.")
    language = None if language == "" else language
    logger.debug(
        f"Processed preferences - Lang: {default_language}, Model: {default_model}, "
        f"AuxiliaryModel: {default_title_generation_model}, WorkflowModel: {default_workflow_model}, "
        f"AutoTitle: {enable_auto_title}, UI Lang: {language}"
    )


    if not username or not email:
        raise ProfileUpdateError("Username and Email cannot be empty.")

    try:
        current_user_obj = user_model.get_user_by_id(user_id)
        if not current_user_obj:
            raise UserNotFoundError(f"User with ID {user_id} not found.")

        username_changed = username != current_user_obj.username
        email_changed = email != current_user_obj.email

        if username_changed:
            existing_user = user_model.get_user_by_username(username)
            if existing_user:
                logger.warning(f"Update failed: Username '{username}' is already taken.")
                raise UsernameTakenError(f"Username '{username}' is already taken.")

        if email_changed:
            existing_user = user_model.get_user_by_email(email)
            if existing_user:
                logger.warning(f"Update failed: Email '{email}' is already registered.")
                raise EmailTakenError(f"Email address '{email}' is already registered.")

        core_info_changed = (
            username_changed or
            email_changed or
            first_name != current_user_obj.first_name or
            last_name != current_user_obj.last_name
        )
        llm_preferences_present = (
            'default_title_generation_model' in data or
            'default_workflow_model' in data
        )
        prefs_changed = (
            default_language != current_user_obj.default_content_language or
            default_model != current_user_obj.default_transcription_model or
            enable_auto_title != current_user_obj.enable_auto_title_generation or
            language != current_user_obj.language or
            (
                llm_preferences_present and (
                    default_title_generation_model != getattr(current_user_obj, 'default_title_generation_model', None) or
                    default_workflow_model != getattr(current_user_obj, 'default_workflow_model', None)
                )
            )
            or (
                live_model_present
                and default_live_transcription_model != getattr(current_user_obj, 'default_live_transcription_model', None)
            )
        )

        if not core_info_changed and not prefs_changed:
            logger.debug("No profile changes were submitted.")
            return

        core_update_performed = False
        if core_info_changed:
            logger.debug("Core profile info changed, attempting update...")
            if user_model.update_user_profile(user_id, username, email, first_name, last_name):
                core_update_performed = True
                logger.debug("Core profile info updated successfully in DB.")
            else:
                logger.debug("Core profile info update: no rows affected (data likely already matched).")
                core_update_performed = True
        else:
            logger.debug("No changes detected in core profile info.")
            core_update_performed = True

        prefs_update_performed = False
        if prefs_changed:
            logger.debug("Preferences changed, attempting update...")
            preference_kwargs = {}
            if 'default_title_generation_model' in data:
                preference_kwargs['default_title_generation_model'] = default_title_generation_model
            if 'default_workflow_model' in data:
                preference_kwargs['default_workflow_model'] = default_workflow_model
            if live_model_present:
                preference_kwargs['default_live_transcription_model'] = default_live_transcription_model
            if user_model.update_user_preferences(
                user_id,
                default_language,
                default_model,
                enable_auto_title,
                language,
                **preference_kwargs,
            ):
                prefs_update_performed = True
                logger.debug("Preferences updated successfully in DB.")
            else:
                logger.warning("update_user_preferences model function returned False. Preferences might not have been saved (or were already set to the target values).")
                prefs_update_performed = True
        else:
            logger.debug("No changes detected in preferences.")
            prefs_update_performed = True

        # --- NEW: Trigger template sync if language changed ---
        if language != current_user_obj.language:
            logger.debug(f"User UI language changed from '{current_user_obj.language}' to '{language}'. Triggering template sync.")
            sync_templates_for_user(user_id)
        # --- END NEW ---

        logger.info(f"Profile update process completed. Core processed: {core_update_performed}, Prefs processed: {prefs_update_performed}")

    except (UserNotFoundError, UsernameTakenError, EmailTakenError, DatabaseUpdateError, ProfileUpdateError) as e:
        raise e
    except MySQLError as db_err:
        logger.error(f"Database error updating profile: {db_err}", exc_info=True)
        if db_err.errno == 1062:
            if 'username' in str(db_err).lower():
                raise UsernameTakenError(f"Username '{username}' is already taken (DB constraint).")
            elif 'email' in str(db_err).lower():
                raise EmailTakenError(f"Email address '{email}' is already registered (DB constraint).")
        raise ProfileUpdateError("A database error occurred while updating the profile.") from db_err
    except Exception as e:
        logger.error(f"Unexpected error updating profile: {e}", exc_info=True)
        raise ProfileUpdateError("An unexpected error occurred while updating the profile.") from e


# --- User Prompt Management ---
def save_user_prompt(user_id: int, title: str, prompt_text: str, color: str = '#ffffff') -> Optional[UserPrompt]:
    """Saves a new custom prompt for the user."""
    logger = get_logger(__name__, user_id=user_id, component="UserService")
    logger.debug(f"Service received color: '{color}' (Type: {type(color)})")
    if not title or not prompt_text:
        raise ValueError("Prompt title and text cannot be empty.")
    try:
        new_prompt = user_prompt_model.add_prompt(user_id, title, prompt_text, color)
        if not new_prompt:
            # This case might be redundant if add_prompt always raises on failure, but it's safe to keep.
            raise PromptManagementError("Failed to save prompt for an unknown reason.")
        return new_prompt
    except MySQLError as db_err:
        logger.error(f"Database error saving prompt: {db_err.msg} (Code: {db_err.errno})", exc_info=True)
        if db_err.errno == 1062: # Duplicate entry
            raise DuplicatePromptError(f"A prompt with the title '{title}' already exists.") from db_err
        elif db_err.errno == 1406: # Data too long
            raise DataLengthError("The provided title or prompt text is too long.") from db_err
        raise PromptManagementError("A database error occurred while saving the prompt.") from db_err
    except Exception as e:
        logger.error(f"Unexpected error saving prompt: {e}", exc_info=True)
        raise PromptManagementError("An unexpected error occurred while saving the prompt.") from e

def get_user_prompts(user_id: int) -> List[UserPrompt]:
    """Retrieves all saved prompts for the user."""
    logger = get_logger(__name__, user_id=user_id, component="UserService")
    try:
        return user_prompt_model.get_prompts_by_user(user_id)
    except MySQLError as db_err:
        logger.error(f"Database error getting prompts: {db_err}", exc_info=True)
        raise PromptManagementError("Database error retrieving prompts.") from db_err
    except Exception as e:
        logger.error(f"Unexpected error getting prompts: {e}", exc_info=True)
        raise PromptManagementError("Unexpected error retrieving prompts.") from e

def update_user_prompt(prompt_id: int, user_id: int, title: str, prompt_text: str, color: str = '#ffffff') -> bool:
    """Updates an existing user prompt."""
    logger = get_logger(__name__, user_id=user_id, component="UserService")
    logger.debug(f"Service received color for update: '{color}' (Type: {type(color)})")
    if not title or not prompt_text:
        raise ValueError("Prompt title and text cannot be empty.")
    try:
        success = user_prompt_model.update_prompt(prompt_id, user_id, title, prompt_text, color)
        if not success:
            if not user_prompt_model.get_prompt_by_id(prompt_id):
                 raise PromptNotFoundError(f"Prompt with ID {prompt_id} not found.")
            else:
                 raise PromptManagementError(f"Failed to update prompt {prompt_id} (check ownership or logs).")
        return True
    except MySQLError as db_err:
        logger.error(f"Database error updating prompt {prompt_id}: {db_err}", exc_info=True)
        raise PromptManagementError("Database error updating prompt.") from db_err
    except Exception as e:
        logger.error(f"Unexpected error updating prompt {prompt_id}: {e}", exc_info=True)
        if isinstance(e, (PromptNotFoundError, PromptManagementError)):
            raise e
        else:
            raise PromptManagementError("Unexpected error updating prompt.") from e

def delete_user_prompt(prompt_id: int, user_id: int) -> bool:
    """Deletes a user prompt."""
    logger = get_logger(__name__, user_id=user_id, component="UserService")
    try:
        success = user_prompt_model.delete_prompt(prompt_id, user_id)
        if not success:
            if not user_prompt_model.get_prompt_by_id(prompt_id):
                 raise PromptNotFoundError(f"Prompt with ID {prompt_id} not found.")
            else:
                 raise PromptManagementError(f"Failed to delete prompt {prompt_id} (check ownership).")
        return True
    except MySQLError as db_err:
        logger.error(f"Database error deleting prompt {prompt_id}: {db_err}", exc_info=True)
        raise PromptManagementError("Database error deleting prompt.") from db_err
    except Exception as e:
        logger.error(f"Unexpected error deleting prompt {prompt_id}: {e}", exc_info=True)
        if isinstance(e, (PromptNotFoundError, PromptManagementError)):
            raise e
        else:
            raise PromptManagementError("Unexpected error deleting prompt.") from e

def get_recent_user_prompts(user_id: int, limit: int = 5) -> List[str]:
    """Retrieves the most recently used distinct workflow prompts for a user."""
    logger = get_logger(__name__, user_id=user_id, component="UserService")
    prompts = []
    try:
        cursor = get_cursor()
        sql = """
            SELECT input_text as workflow_prompt
            FROM llm_operations
            WHERE user_id = %s
              AND operation_type = 'workflow'
              AND input_text IS NOT NULL
              AND input_text != ''
              AND completed_at IS NOT NULL
            GROUP BY input_text
            ORDER BY MAX(completed_at) DESC
            LIMIT %s
        """
        cursor.execute(sql, (user_id, limit))
        rows = cursor.fetchall()
        prompts = [row['workflow_prompt'] for row in rows]
        logger.debug(f"Retrieved {len(prompts)} recent prompts from llm_operations.")
    except MySQLError as db_err:
        logger.error(f"Database error getting recent prompts: {db_err}", exc_info=True)
        prompts = []
    except Exception as e:
        logger.error(f"Unexpected error getting recent prompts: {e}", exc_info=True)
        prompts = []
    finally:
        # The cursor is managed by the application context, so we don't close it here.
        pass
    return prompts

def get_prompt_by_id_internal(prompt_id: int) -> Optional[UserPrompt]:
    """Internal helper to get prompt by ID without user check."""
    try:
        return user_prompt_model.get_prompt_by_id(prompt_id)
    except Exception:
        return None

# --- NEW: Template Synchronization Service ---

def sync_templates_for_user(user_id: int) -> None:
    """
    Synchronizes admin-defined templates to a specific user's personal prompt collection.

    - Copies new templates that match the user's language.
    - Updates existing synced prompts if the source template has changed.
    - Deletes user's synced prompts if the source template was deleted.
    """
    logger = get_logger(__name__, user_id=user_id, component="UserService")
    logger.debug("Starting template synchronization.")

    try:
        user = user_model.get_user_by_id(user_id)
        if not user:
            logger.error("User not found, cannot sync templates.")
            return

        # 1. Get all relevant admin templates (matching user lang or 'all')
        user_lang = user.language
        admin_templates = template_prompt_model.get_templates(language=user.language)
        admin_template_map = {t.id: t for t in admin_templates}
        logger.debug(f"Found {len(admin_templates)} applicable admin templates for language '{user_lang}'.")

        # 2. Get user's existing prompts that were synced from a template
        user_synced_prompts_map = user_prompt_model.get_user_synced_prompts_map(user_id)
        logger.debug(f"Found {len(user_synced_prompts_map)} existing synced prompts for user.")

        # 3. Synchronize: Add new, update existing
        for template_id, template in admin_template_map.items():
            existing_user_prompt = user_synced_prompts_map.get(template_id)

            if existing_user_prompt:
                # This template exists in the user's collection, check for updates
                if (existing_user_prompt.title != template.title or
                    existing_user_prompt.prompt_text != template.prompt_text or
                    existing_user_prompt.color != template.color):
                    
                    logger.debug(f"Updating user prompt ID {existing_user_prompt.id} from source template ID {template_id}.")
                    user_prompt_model.update_synced_prompt(
                        prompt_id=existing_user_prompt.id,
                        title=template.title,
                        prompt_text=template.prompt_text,
                        color=template.color
                    )
            else:
                # This is a new template for this user, copy it
                logger.debug(f"Copying new template ID {template_id} ('{template.title}') to user.")
                user_prompt_model.add_prompt(
                    user_id=user_id,
                    title=template.title,
                    prompt_text=template.prompt_text,
                    color=template.color,
                    source_template_id=template.id
                )

        # 4. Synchronize: Remove deleted (Handled by ON DELETE CASCADE)
        # When a template_prompt is deleted, the corresponding user_prompts
        # are automatically removed by the database, so no action is needed here.

        logger.info("Template synchronization complete.")

    except Exception as e:
        logger.error(f"An unexpected error occurred during template sync: {e}", exc_info=True)


def sync_templates_for_all_users() -> None:
    """
    Triggers the template synchronization process for every user in the system.
    This is typically called after an admin modifies the template collection.
    """
    logger = get_logger(__name__, component="UserService")
    logger.info("Starting template synchronization for ALL users.")
    try:
        all_user_ids = user_prompt_model.get_all_user_ids()
        logger.debug(f"Found {len(all_user_ids)} users to sync.")
        for user_id in all_user_ids:
            sync_templates_for_user(user_id)
        logger.info("Finished syncing templates for all users.")
    except Exception as e:
        logger.error(f"An unexpected error occurred during all-user sync: {e}", exc_info=True)

def handle_new_user_template_sync(user_id: int) -> None:
    """
    Handles the initial population of templates for a new user.
    This is just a clear wrapper around the main sync function.
    """
    logger = get_logger(__name__, user_id=user_id, component="UserService")
    logger.debug("Triggering initial template population for new user.")
    sync_templates_for_user(user_id)
