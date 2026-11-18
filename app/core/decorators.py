# app/core/decorators.py
# Defines custom decorators used throughout the application, primarily for access control.

import logging
from functools import wraps
from typing import Callable, Any, Tuple, Optional
from flask import abort, g, current_app # g for request context storage, current_app for context needs
from flask_babel import gettext as _

# Import Flask-Login proxy for current user
from flask_login import current_user

# Import models and services needed for checks
try:
    from app.models.user import User
    from app.models.role import Role
    from app.services import usage_service
except ImportError:
    logging.critical("[CORE:Decorators] Failed to import User/Role models or user_utils. Decorators will likely fail.")
    User = None # type: ignore
    Role = None # type: ignore
    user_utils = None # type: ignore

# --- Admin Access Decorator ---
def admin_required(func: Callable) -> Callable:
    """
    Decorator for Flask routes that require administrator privileges.
    Checks if the user is logged in and their role has 'access_admin_panel' permission.
    Relies on `g.user` and `g.role` being populated by a @before_request hook.
    """
    @wraps(func)
    def decorated_view(*args: Any, **kwargs: Any) -> Any:
        user: Optional[User] = getattr(g, 'user', None)
        role: Optional[Role] = getattr(g, 'role', None)
        endpoint_name = func.__name__

        if not user or not user.is_authenticated:
            logging.warning(f"[AUTH:AdminRequired] Access denied to '{endpoint_name}': User not authenticated.")
            abort(403)

        from app.services import access_service
        if not access_service.is_team_mode():
            logging.warning(f"[AUTH:AdminRequired] Access denied to '{endpoint_name}': the Admin panel is only available in team mode.")
            abort(403)

        if not role or not getattr(role, 'access_admin_panel', False):
            username = user.username if user else 'Unknown'
            user_id = user.id if user else 'N/A'
            role_name = role.name if role else 'None'
            logging.warning(f"[AUTH:AdminRequired] Access denied to '{endpoint_name}': User '{username}' (ID: {user_id}, Role: '{role_name}') lacks 'access_admin_panel' permission.")
            abort(403)

        logging.debug(f"[AUTH:AdminRequired] Admin access granted for user '{user.username}' (ID: {user.id}) to '{endpoint_name}'.")
        return func(*args, **kwargs)
    return decorated_view

def permission_required(permission_name: str) -> Callable:
    """
    Decorator factory to check if the logged-in user's role has a specific boolean permission.
    Example Usage: @permission_required('allow_large_files')
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def decorated_view(*args: Any, **kwargs: Any) -> Any:
            user: Optional[User] = getattr(g, 'user', None)
            role: Optional[Role] = getattr(g, 'role', None)
            endpoint_name = func.__name__

            if not user or not user.is_authenticated:
                logging.warning(f"[AUTH:PermissionRequired] Permission '{permission_name}' denied for '{endpoint_name}': User not authenticated.")
                abort(403)

            has_perm = False
            if role:
                # Include 'manage_' prefix for permissions check
                if permission_name.startswith(('use_', 'allow_', 'access_', 'manage_')):
                     has_perm = getattr(role, permission_name, False)
                else:
                     logging.error(f"[AUTH:PermissionRequired] Invalid permission name format used in decorator for '{endpoint_name}': '{permission_name}'. Check starts with use_, allow_, access_, manage_.")
                     abort(500, description="Server configuration error checking permissions.")

            if not has_perm:
                username = user.username if user else 'Unknown'
                user_id = user.id if user else 'N/A'
                role_name = role.name if role else 'None'
                logging.warning(f"[AUTH:PermissionRequired] Permission denied for '{endpoint_name}': User '{username}' (ID: {user_id}, Role: '{role_name}') lacks '{permission_name}' permission.")
                abort(403)

            logging.debug(f"[AUTH:PermissionRequired] Permission '{permission_name}' granted for user '{user.username}' (ID: {user.id}) to '{endpoint_name}'.")
            return func(*args, **kwargs)
        return decorated_view
    return decorator

def check_permission(user: Optional[User], permission_name: str) -> bool:
    """
    Checks if a given User object has a specific boolean permission via their role.
    Safe to call with None user.
    """
    if not user or not user.is_authenticated or not user.role:
        return False
    return user.has_permission(permission_name)

def check_usage_limits(
    user: Optional[User],
    cost_to_add: float = 0.0,
    minutes_to_add: float = 0.0,
    is_workflow: bool = False,
    live_minutes_to_add: float = 0.0,
) -> Tuple[bool, str]:
    """
    Checks if initiating a new job would exceed the user's role-based usage limits.

    Args:
        user: The User object to check limits for.
        cost_to_add: The estimated cost of the new job.
        minutes_to_add: The estimated duration in minutes of the new job.
        is_workflow: If True, checks workflow count limits.
        live_minutes_to_add: Reserved live-transcription minutes for the job.

    Returns:
        A tuple: (allowed: bool, reason: str).
    """
    if not user or not user.is_authenticated or not user.role:
        return False, _("User not authenticated or role not assigned.")
    if usage_service is None:
        logging.error("[CORE:Decorators] Cannot check usage limits: usage_service not available.")
        return False, _("Server configuration error checking usage limits.")

    role = user.role
    reason = _("Usage limits check passed.")
    log_prefix = f"[AUTH:UsageCheck:User:{user.id}]"

    try:
        usage_stats = usage_service.get_user_usage(user.id)

        # --- Check Limits (only if limit > 0, meaning it's enforced) ---
        if role.limit_daily_cost > 0 and (usage_stats['daily']['cost'] + cost_to_add) > role.limit_daily_cost:
            return False, _("You have reached your fair use limit.")
        if role.limit_weekly_cost > 0 and (usage_stats['weekly']['cost'] + cost_to_add) > role.limit_weekly_cost:
            return False, _("You have reached your fair use limit.")
        if role.limit_monthly_cost > 0 and (usage_stats['monthly']['cost'] + cost_to_add) > role.limit_monthly_cost:
            return False, _("You have reached your fair use limit.")

        if role.limit_daily_minutes > 0 and (usage_stats['daily']['minutes'] + minutes_to_add) > role.limit_daily_minutes:
            return False, _("You have reached your fair use limit.")
        if role.limit_weekly_minutes > 0 and (usage_stats['weekly']['minutes'] + minutes_to_add) > role.limit_weekly_minutes:
            return False, _("You have reached your fair use limit.")
        if role.limit_monthly_minutes > 0 and (usage_stats['monthly']['minutes'] + minutes_to_add) > role.limit_monthly_minutes:
            return False, _("You have reached your fair use limit.")

        if role.limit_daily_live_minutes > 0 and (usage_stats['daily']['live_minutes'] + live_minutes_to_add) > role.limit_daily_live_minutes:
            return False, _("You have reached your fair use limit.")
        if role.limit_weekly_live_minutes > 0 and (usage_stats['weekly']['live_minutes'] + live_minutes_to_add) > role.limit_weekly_live_minutes:
            return False, _("You have reached your fair use limit.")
        if role.limit_monthly_live_minutes > 0 and (usage_stats['monthly']['live_minutes'] + live_minutes_to_add) > role.limit_monthly_live_minutes:
            return False, _("You have reached your fair use limit.")

        if is_workflow:
            if role.limit_daily_workflows > 0 and (usage_stats['daily']['workflows'] + 1) > role.limit_daily_workflows:
                return False, _("You have reached your fair use limit.")
            if role.limit_weekly_workflows > 0 and (usage_stats['weekly']['workflows'] + 1) > role.limit_weekly_workflows:
                return False, _("You have reached your fair use limit.")
            if role.limit_monthly_workflows > 0 and (usage_stats['monthly']['workflows'] + 1) > role.limit_monthly_workflows:
                return False, _("You have reached your fair use limit.")

        logging.debug(f"{log_prefix} Usage limits check passed.")
        return True, _("Usage limits check passed.")

    except Exception as e:
         logging.error(f"{log_prefix} Error checking usage limits: {e}", exc_info=True)
         return False, _("An error occurred while checking usage limits.")


LIVE_ACCESS_PERMISSIONS = (
    'use_api_openai',
    'use_api_openai_live_transcribe',
    'use_api_openrouter',
    'use_api_google_gemini',
)


def has_live_access(user: Optional[User]) -> bool:
    """Whether ``user`` may open Live transcription (any live-capable provider)."""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    return any(check_permission(user, permission) for permission in LIVE_ACCESS_PERMISSIONS)
