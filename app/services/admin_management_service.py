# app/services/admin_management_service.py
# Contains business logic for administrator-specific actions (user/role management, logs).

import logging
import os
import math
from typing import List, Dict, Any, Optional, Tuple

# Import necessary components from the application
from flask import current_app # To access config and app context
from flask_login import login_user
from app import bcrypt # Import the bcrypt instance from app extensions
from app.models import user as user_model # Models now use MySQL
from app.models import transcription_utils # Import the new utils file
from app.models import role as role_model
from app.models import user_utils # Import the new utils file
from app.models import template_prompt as template_prompt_model
from app.models import user_prompt as user_prompt_model
from app.models.user import User # Import User class for type hinting
from app.models.role import Role
from app.models.template_prompt import TemplatePrompt
from app.services import auth_service, user_service, admin_metrics_service
from app.services.exceptions import AdminServiceError

# Import MySQL error class for potential specific checks if needed
from mysql.connector import Error as MySQLError

# --- User Management Functions (Admin Perspective) ---
def list_paginated_users(page: int, per_page: int = 50) -> Tuple[List[User], Dict[str, Any]]:
    """
    Retrieves a paginated list of users with details for the admin panel.
    Includes role ID for inline editing.
    """
    log_prefix = "[SERVICE:Admin:PaginatedUsers]"
    users_data = []
    pagination_meta = {
        'total_users': 0,
        'total_pages': 0,
        'current_page': page,
        'per_page': per_page
    }

    try:
        with current_app.app_context():
            total_users = user_utils.count_all_users()
            pagination_meta['total_users'] = total_users
            pagination_meta['total_pages'] = math.ceil(total_users / per_page) if per_page > 0 else 0
            page = max(1, min(page, pagination_meta['total_pages'] if pagination_meta['total_pages'] > 0 else 1))
            pagination_meta['current_page'] = page
            offset = (page - 1) * per_page
            # Fetch data including role_id
            users_data = user_utils.get_paginated_users_with_details(offset, per_page) # Model returns minutes now

            logging.info(f"{log_prefix} Retrieved page {page}/{pagination_meta['total_pages']} ({len(users_data)} users) of {total_users} total users.")
            return users_data, pagination_meta

    except MySQLError as db_err:
        logging.error(f"{log_prefix} Database error listing paginated users: {db_err}", exc_info=True)
        raise AdminServiceError("Failed to list users due to a database error.") from db_err
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error listing paginated users: {e}", exc_info=True)
        raise AdminServiceError(f"Failed to list users: {e}") from e

def get_user_details_with_stats(user_id: int) -> Optional[Dict[str, Any]]:
    """
    Retrieves detailed information for a single user, including calculated usage statistics (minutes).
    Requires app context for database access (MySQL).
    """
    log_prefix = f"[SERVICE:Admin:User:{user_id}]"
    try:
        with current_app.app_context():
            user = user_model.get_user_by_id(user_id)
            if not user:
                logging.warning(f"{log_prefix} User not found when getting details.")
                return None

            role_obj = user.role

            # Get usage stats (includes total_minutes, monthly_minutes, monthly_workflows)
            usage_stats = user_utils.get_user_usage_stats(user_id)
            error_count = transcription_utils.count_user_errors(user_id)

        user_details = {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'role': role_obj,
            'created_at': user.created_at,
            'stats': {
                'transcription_count': usage_stats.get('total_transcriptions', 0),
                'error_count': error_count,
                'total_audio_length_minutes': usage_stats.get('total_minutes', 0.0), # Use total_minutes
                'monthly_transcriptions': usage_stats.get('monthly_transcriptions', 0),
                'monthly_audio_length_minutes': usage_stats.get('monthly_minutes', 0.0), # Use monthly_minutes
                'monthly_workflows': usage_stats.get('monthly_workflows', 0) # Add workflow stats
            }
        }
        logging.info(f"{log_prefix} Retrieved details and stats.")
        return user_details

    except MySQLError as db_err:
        logging.error(f"{log_prefix} Database error getting details: {db_err}", exc_info=True)
        raise AdminServiceError(f"Failed to get user details due to a database error.") from db_err
    except Exception as e:
        logging.error(f"{log_prefix} Error getting details: {e}", exc_info=True)
        raise AdminServiceError(f"Failed to get user details: {e}") from e

def get_user_details_for_admin(user_id: int) -> Optional[Dict[str, Any]]:
    """
    Retrieves comprehensive details for a user, including stats and full history (minutes).
    Designed for the admin detailed user view. Shows ALL history items, including hidden.
    Requires app context.
    """
    log_prefix = f"[SERVICE:Admin:UserDetails:{user_id}]"
    try:
        with current_app.app_context():
            user_details = get_user_details_with_stats(user_id)
            if not user_details:
                return None

            # Fetch detailed usage metrics
            usage_metrics = admin_metrics_service.get_user_usage_metrics(user_id)
            user_details['usage_metrics'] = usage_metrics

            # Fetch transcription history (including hidden)
            transcription_history = transcription_utils.get_all_transcriptions_for_admin(user_id, limit=None)
            user_details['history'] = transcription_history

            # Filter for workflow history
            workflow_history = [
                item for item in transcription_history
                if item.get('workflow_result') is not None or item.get('workflow_status', 'idle') != 'idle'
            ]
            user_details['workflow_history'] = workflow_history

            logging.info(f"{log_prefix} Retrieved comprehensive details including {len(transcription_history)} history items and {len(workflow_history)} workflow items.")
            return user_details

    except MySQLError as db_err:
        logging.error(f"{log_prefix} Database error getting comprehensive details: {db_err}", exc_info=True)
        raise AdminServiceError("Failed to get user details due to a database error.") from db_err
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error getting comprehensive details: {e}", exc_info=True)
        raise AdminServiceError(f"Failed to get user details: {e}") from e

def admin_create_user(username: str, password: str, email: str, role_name: str = 'beta-tester') -> User:
    """
    Allows an administrator to create a new user account with a specified role.
    Handles password hashing and database insertion via auth_service (using MySQL).
    Raises AdminServiceError on failure (e.g., username taken, invalid role).
    Requires app context.
    """
    log_prefix = "[SERVICE:Admin]"
    logging.info(f"{log_prefix} Admin attempting to create user '{username}' with role '{role_name}'.")
    try:
        with current_app.app_context():
            role = role_model.get_role_by_name(role_name)
            if not role:
                 logging.error(f"{log_prefix} Cannot create user '{username}': Role '{role_name}' does not exist.")
                 raise AdminServiceError(f"Role '{role_name}' does not exist.")

            new_user = auth_service.create_user(username, password, email, role_name)

            if not new_user:
                existing_user_name = user_model.get_user_by_username(username)
                if existing_user_name:
                    logging.warning(f"{log_prefix} Failed to create user '{username}': Username already taken.")
                    raise AdminServiceError(f"Username '{username}' is already taken.")
                existing_user_email = user_model.get_user_by_email(email)
                if existing_user_email:
                    logging.warning(f"{log_prefix} Failed to create user with email '{email}': Email already taken.")
                    raise AdminServiceError(f"Email '{email}' is already taken.")
                logging.error(f"{log_prefix} Failed to create user '{username}' due to unknown database error (check model logs).")
                raise AdminServiceError(f"Failed to create user '{username}' due to a database error.")

        logging.info(f"{log_prefix} Admin successfully created user '{username}' (ID: {new_user.id}).")
        return new_user

    except Exception as e:
        logging.error(f"{log_prefix} Error during admin creation of user '{username}': {e}", exc_info=True)
        if isinstance(e, (AdminServiceError, auth_service.AuthServiceError)):
            raise e
        else:
            raise AdminServiceError(f"An unexpected error occurred during admin user creation: {e}") from e

def admin_delete_user(user_id_to_delete: int, current_admin_id: int) -> bool:
    """
    Allows an administrator to delete another user account. Prevents self-deletion.
    Raises AdminServiceError if the user cannot be deleted (not found, self-delete).
    Returns True on successful deletion. Uses MySQL backend via models.
    Requires app context.
    """
    log_prefix = f"[SERVICE:Admin:Delete]"
    logging.warning(f"{log_prefix} Admin (ID: {current_admin_id}) attempting to delete user ID {user_id_to_delete}.")

    if user_id_to_delete == current_admin_id:
        logging.error(f"{log_prefix} Admin (ID: {current_admin_id}) cannot delete their own account.")
        raise AdminServiceError("Administrators cannot delete their own account.")

    try:
        with current_app.app_context():
            user_to_delete = user_model.get_user_by_id(user_id_to_delete)
            if not user_to_delete:
                logging.warning(f"{log_prefix} Attempt to delete non-existent user ID {user_id_to_delete} by admin {current_admin_id}.")
                raise AdminServiceError("User to delete not found.")

            from app.services import access_service
            if access_service.get_owner_id() == user_to_delete.id:
                logging.error(f"{log_prefix} Admin (ID: {current_admin_id}) attempted to delete the owner account (ID: {user_id_to_delete}).")
                raise AdminServiceError("Cannot delete the owner account.")

            success = user_model.delete_user_by_id(user_id_to_delete)

        if success:
            logging.info(f"{log_prefix} Admin (ID: {current_admin_id}) successfully deleted user ID {user_id_to_delete}.")
            return True
        else:
            logging.error(f"{log_prefix} Failed to delete user ID {user_id_to_delete} from database (model returned False).")
            raise AdminServiceError("Failed to delete user from database.")

    except MySQLError as db_err:
        logging.error(f"{log_prefix} Database error during admin deletion of user ID {user_id_to_delete}: {db_err}", exc_info=True)
        raise AdminServiceError(f"A database error occurred during admin user deletion.") from db_err
    except Exception as e:
        logging.error(f"{log_prefix} Error during admin deletion of user ID {user_id_to_delete}: {e}", exc_info=True)
        if not isinstance(e, AdminServiceError):
            raise AdminServiceError(f"An unexpected error occurred during admin user deletion: {e}") from e
        else:
            raise e

def admin_reset_user_password(user_id_to_reset: int, new_password: str, current_admin_id: int) -> bool:
    """
    Allows an administrator to reset a user's password.
    Validates password length and handles hashing. Uses MySQL backend via models.
    Raises AdminServiceError on failure (user not found, validation error).
    Returns True on successful password reset.
    Requires app context.
    """
    log_prefix = f"[SERVICE:Admin:ResetPwd]"
    logging.info(f"{log_prefix} Admin (ID: {current_admin_id}) attempting to reset password for user ID {user_id_to_reset}.")

    if not new_password or len(new_password) < 8:
        logging.warning(f"{log_prefix} Password reset failed for user {user_id_to_reset}: Password too short.")
        raise AdminServiceError("New password must be at least 8 characters long.")

    try:
        with current_app.app_context():
            user = user_model.get_user_by_id(user_id_to_reset)
            if not user:
                logging.warning(f"{log_prefix} Password reset failed: User ID {user_id_to_reset} not found.")
                raise AdminServiceError("User not found for password reset.")

            hashed_password = bcrypt.generate_password_hash(
                new_password, current_app.config['BCRYPT_LOG_ROUNDS']
            ).decode('utf-8')
            logging.debug(f"{log_prefix} New password hashed for user ID {user_id_to_reset}.")

            success = user_model.update_user_password_hash(user_id_to_reset, hashed_password)

        if success:
            logging.info(f"{log_prefix} Admin (ID: {current_admin_id}) successfully reset password for user ID {user_id_to_reset}.")
            return True
        else:
            logging.error(f"{log_prefix} Failed to update password hash for user ID {user_id_to_reset} in database (model returned False).")
            raise AdminServiceError("Failed to update password hash in database.")

    except MySQLError as db_err:
        logging.error(f"{log_prefix} Database error during admin password reset for user ID {user_id_to_reset}: {db_err}", exc_info=True)
        raise AdminServiceError(f"A database error occurred during admin password reset.") from db_err
    except Exception as e:
        logging.error(f"{log_prefix} Error during admin password reset for user ID {user_id_to_reset}: {e}", exc_info=True)
        if not isinstance(e, AdminServiceError):
            raise AdminServiceError(f"An unexpected error occurred during admin password reset: {e}") from e
        else:
            raise e

def update_user_role_admin(user_id_to_update: int, new_role_id: int, current_admin_id: int) -> None:
    """
    Allows an administrator to update a user's role.
    Includes checks to prevent self-role change and changing the initial admin's role.
    Requires app context.
    """
    log_prefix = f"[SERVICE:Admin:UpdateRole:{user_id_to_update}]"
    logging.info(f"{log_prefix} Admin (ID: {current_admin_id}) attempting to set role ID to {new_role_id}.")

    if user_id_to_update == current_admin_id:
        logging.error(f"{log_prefix} Admin (ID: {current_admin_id}) cannot change their own role.")
        raise AdminServiceError("Administrators cannot change their own role.")

    try:
        with current_app.app_context():
            user_to_update = user_model.get_user_by_id(user_id_to_update)
            if not user_to_update:
                logging.warning(f"{log_prefix} Attempt to update role for non-existent user ID {user_id_to_update}.")
                raise AdminServiceError("User not found.")

            from app.services import access_service
            if access_service.get_owner_id() == user_to_update.id:
                logging.error(f"{log_prefix} Admin (ID: {current_admin_id}) attempted to change the role of the owner account (ID: {user_id_to_update}).")
                raise AdminServiceError("Cannot change the role of the owner account.")

            new_role = role_model.get_role_by_id(new_role_id)
            if not new_role:
                logging.warning(f"{log_prefix} Attempt to assign non-existent role ID {new_role_id}.")
                raise AdminServiceError("The selected role does not exist.")

            success = user_model.update_user_role(user_id_to_update, new_role_id)

            if success:
                logging.info(f"{log_prefix} Admin (ID: {current_admin_id}) successfully updated role to '{new_role.name}' (ID: {new_role_id}).")
                
                # --- MODIFIED: Re-authenticate user to refresh session ---
                try:
                    login_user(user_to_update)
                    logging.info(f"{log_prefix} User {user_to_update.id} re-authenticated to refresh session after role change.")
                except Exception as e:
                    logging.error(f"{log_prefix} Failed to re-authenticate user {user_to_update.id} after role change: {e}", exc_info=True)
                # --- END MODIFIED ---
            else:
                logging.error(f"{log_prefix} Failed to update role for user ID {user_id_to_update} (model returned False).")
                raise AdminServiceError("Failed to update user role in the database.")

    except MySQLError as db_err:
        logging.error(f"{log_prefix} Database error updating user role: {db_err}", exc_info=True)
        raise AdminServiceError("A database error occurred while updating the user role.") from db_err
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error updating user role: {e}", exc_info=True)
        if isinstance(e, AdminServiceError):
            raise e
        else:
            raise AdminServiceError(f"An unexpected error occurred while updating the user role: {e}") from e

# --- Role Management Functions ---
def get_all_roles() -> List[Dict[str, Any]]:
    """
    Retrieves all defined roles from the database, including the count of users in each role.
    Requires app context.
    """
    log_prefix = "[SERVICE:Admin:Roles]"
    roles_with_counts = []
    try:
        with current_app.app_context():
            roles = role_model.get_all_roles()
            for role in roles:
                user_count = user_model.count_users_by_role_id(role.id)
                role_dict = role.__dict__
                role_dict['user_count'] = user_count
                roles_with_counts.append(role_dict)
            logging.info(f"{log_prefix} Retrieved {len(roles_with_counts)} roles with user counts.")
            return roles_with_counts
    except MySQLError as db_err:
        logging.error(f"{log_prefix} Database error retrieving roles: {db_err}", exc_info=True)
        raise AdminServiceError("Failed to retrieve roles due to a database error.") from db_err
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error retrieving roles: {e}", exc_info=True)
        raise AdminServiceError(f"Failed to retrieve roles: {e}") from e


def create_role(role_data: Dict[str, Any]) -> Optional[Role]:
    """
    Creates a new role using the provided data.
    Requires app context.
    """
    log_prefix = "[SERVICE:Admin:CreateRole]"
    role_name = role_data.get('name')
    if not role_name:
        raise ValueError("Role name is required.")

    logging.info(f"{log_prefix} Attempting to create role '{role_name}'.")
    try:
        with current_app.app_context():
            existing_role = role_model.get_role_by_name(role_name)
            if existing_role:
                logging.warning(f"{log_prefix} Role name '{role_name}' already exists.")
                raise AdminServiceError(f"Role name '{role_name}' already exists.")

            permissions = {k: v for k, v in role_data.items() if k not in ['name', 'description']}

            new_role = role_model.create_role(
                name=role_name,
                description=role_data.get('description'),
                permissions=permissions
            )

            if new_role:
                logging.info(f"{log_prefix} Role '{role_name}' created successfully (ID: {new_role.id}).")
                return new_role
            else:
                logging.error(f"{log_prefix} Role creation failed (model returned None).")
                raise AdminServiceError("Failed to create role in database.")

    except MySQLError as db_err:
        logging.error(f"{log_prefix} Database error creating role '{role_name}': {db_err}", exc_info=True)
        if db_err.errno == 1062:
             raise AdminServiceError(f"Role name '{role_name}' already exists (DB constraint).") from db_err
        else:
             raise AdminServiceError("Failed to create role due to a database error.") from db_err
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error creating role '{role_name}': {e}", exc_info=True)
        if isinstance(e, AdminServiceError):
            raise e
        else:
            raise AdminServiceError(f"An unexpected error occurred while creating the role: {e}") from e


def update_role(role_id: int, role_data: Dict[str, Any]) -> bool:
    """
    Updates an existing role with the provided data.
    Requires app context.
    """
    log_prefix = f"[SERVICE:Admin:UpdateRole:{role_id}]"
    role_name = role_data.get('name')
    if not role_name:
        raise ValueError("Role name is required for update.")

    logging.info(f"{log_prefix} Attempting to update role to name '{role_name}'.")
    try:
        with current_app.app_context():
            target_role = role_model.get_role_by_id(role_id)
            if not target_role:
                 raise AdminServiceError(f"Role with ID {role_id} not found.")

            if role_name != target_role.name:
                existing_role = role_model.get_role_by_name(role_name)
                if existing_role:
                    logging.warning(f"{log_prefix} Role name '{role_name}' already exists.")
                    raise AdminServiceError(f"Role name '{role_name}' already exists.")

            success = role_model.update_role(role_id, role_data)

            if success:
                logging.info(f"{log_prefix} Role updated successfully.")
                return True
            else:
                if role_name != target_role.name and role_model.get_role_by_name(role_name):
                     raise AdminServiceError(f"Role name '{role_name}' already exists (DB constraint during update).")
                else:
                     logging.error(f"{log_prefix} Role update failed (model returned False).")
                     raise AdminServiceError("Failed to update role in database.")

    except MySQLError as db_err:
        logging.error(f"{log_prefix} Database error updating role '{role_name}': {db_err}", exc_info=True)
        if db_err.errno == 1062:
             raise AdminServiceError(f"Role name '{role_name}' already exists (DB constraint).") from db_err
        else:
             raise AdminServiceError("Failed to update role due to a database error.") from db_err
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error updating role '{role_name}': {e}", exc_info=True)
        if isinstance(e, AdminServiceError):
            raise e
        else:
            raise AdminServiceError(f"An unexpected error occurred while updating the role: {e}") from e


def delete_role(role_id: int) -> None:
    """
    Deletes a role after performing safety checks.
    Requires app context.
    """
    log_prefix = f"[SERVICE:Admin:DeleteRole:{role_id}]"
    logging.warning(f"{log_prefix} Attempting to delete role.")
    try:
        with current_app.app_context():
            success, message = role_model.delete_role(role_id)
            if not success:
                logging.warning(f"{log_prefix} Role deletion failed: {message}")
                raise AdminServiceError(message)

        logging.info(f"{log_prefix} Role deleted successfully.")
    except MySQLError as db_err:
        logging.error(f"{log_prefix} Database error deleting role: {db_err}", exc_info=True)
        raise AdminServiceError("Failed to delete role due to a database error.") from db_err
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error deleting role: {e}", exc_info=True)
        if isinstance(e, AdminServiceError):
            raise e
        else:
            raise AdminServiceError(f"An unexpected error occurred while deleting the role: {e}") from e


# --- Template Prompt Management ---

def get_template_prompts(language: Optional[str] = None, include_usage: bool = False) -> List[TemplatePrompt]:
    """Retrieves template prompts, optionally filtered by language."""
    log_prefix = "[SERVICE:Admin:TemplatePrompts]"
    try:
        with current_app.app_context():
            templates = template_prompt_model.get_templates(language=language)
            if include_usage and language is None:
                usage_stats = template_prompt_model.get_template_usage_stats()
                for template in templates:
                    stats = usage_stats.get(template.id, {'unique_users': 0, 'total_uses': 0})
                    template.unique_user_count = stats['unique_users']
                    template.total_usage_count = stats['total_uses']
            return templates
    except MySQLError as db_err:
        logging.error(f"{log_prefix} Database error retrieving template prompts: {db_err}", exc_info=True)
        raise AdminServiceError("Database error retrieving template prompts.") from db_err
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error retrieving template prompts: {e}", exc_info=True)
        raise AdminServiceError("Unexpected error retrieving template prompts.") from e

def add_template_prompt(title: str, prompt_text: str, language: Optional[str] = None, color: str = '#ffffff') -> Optional[TemplatePrompt]:
    """Adds a new template prompt and triggers sync for all users."""
    log_prefix = "[SERVICE:Admin:TemplatePrompts]"
    if not title or not prompt_text:
        raise ValueError("Template title and text cannot be empty.")
    try:
        with current_app.app_context():
            new_template = template_prompt_model.add_template(title, prompt_text, language, color)
            if not new_template:
                raise AdminServiceError("Failed to save template prompt to database.")
            
            logging.info(f"{log_prefix} New template created. Triggering sync for all users.")
            user_service.sync_templates_for_all_users()

            return new_template
    except MySQLError as db_err:
        logging.error(f"{log_prefix} Database error adding template prompt: {db_err}", exc_info=True)
        raise AdminServiceError("Database error adding template prompt.") from db_err
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error adding template prompt: {e}", exc_info=True)
        raise AdminServiceError("Unexpected error adding template prompt.") from e

def update_template_prompt(prompt_id: int, title: str, prompt_text: str, language: Optional[str] = None, color: str = '#ffffff') -> bool:
    """Updates an existing template prompt and triggers sync for all users."""
    log_prefix = f"[SERVICE:Admin:TemplatePrompts:{prompt_id}]"
    if not title or not prompt_text:
        raise ValueError("Template title and text cannot be empty.")
    try:
        with current_app.app_context():
            success = template_prompt_model.update_template(prompt_id, title, prompt_text, language, color)
            if not success:
                if not template_prompt_model.get_template_by_id(prompt_id):
                    raise AdminServiceError(f"Template prompt with ID {prompt_id} not found.")
                else:
                    raise AdminServiceError(f"Failed to update template prompt {prompt_id}.")
            
            logging.info(f"{log_prefix} Template updated. Triggering sync for all users.")
            user_service.sync_templates_for_all_users()
            
            return True
    except MySQLError as db_err:
        logging.error(f"{log_prefix} Database error updating template prompt: {db_err}", exc_info=True)
        raise AdminServiceError("Database error updating template prompt.") from db_err
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error updating template prompt: {e}", exc_info=True)
        if isinstance(e, AdminServiceError):
            raise e
        else:
            raise AdminServiceError("Unexpected error updating template prompt.") from e

def delete_template_prompt(prompt_id: int) -> bool:
    """Deletes a template prompt and also removes it from all users' saved workflows."""
    log_prefix = f"[SERVICE:Admin:TemplatePrompts:{prompt_id}]"
    try:
        with current_app.app_context():
            # First, delete all user prompts that were created from this template.
            # This must happen before deleting the template itself due to ON DELETE SET NULL constraint.
            deleted_user_prompts_count = user_prompt_model.delete_prompts_by_source_id(prompt_id)
            if deleted_user_prompts_count == -1: # Check for error from model function
                raise AdminServiceError(f"Failed to delete associated user workflows for template {prompt_id}.")
            logging.info(f"{log_prefix} Deleted {deleted_user_prompts_count} user workflows linked to this template.")

            # Now, delete the master template
            success = template_prompt_model.delete_template(prompt_id)
            if not success:
                # This case might happen if the template was deleted by another process between the two calls.
                # We can log a warning but don't need to raise an error, as the end goal (template is gone) is achieved.
                logging.warning(f"{log_prefix} Template with ID {prompt_id} was not found for deletion, but proceeding as it might have been deleted already.")

            return True
    except MySQLError as db_err:
        logging.error(f"{log_prefix} Database error deleting template prompt: {db_err}", exc_info=True)
        raise AdminServiceError("Database error deleting template prompt.") from db_err
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error deleting template prompt: {e}", exc_info=True)
        if isinstance(e, AdminServiceError):
            raise e
        else:
            raise AdminServiceError("Unexpected error deleting template prompt.") from e
