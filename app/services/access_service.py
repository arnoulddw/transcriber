# app/services/access_service.py
"""Instance-wide access settings: personal vs. team mode, sign-in and sign-ups.

Personal mode (``single``) always has exactly one usable account, the owner.
While the owner has no password, every browser request is signed in as the
owner automatically. Team mode (``multi``) is the full multi-user setup.

Values set in the environment (``DEPLOYMENT_MODE``, ``ALLOW_REGISTRATION``,
``ADMIN_PASSWORD``) win over values stored in the database, and the matching
controls in the app are shown as locked.
"""

import logging
import time
from typing import Any, Dict, Optional, Tuple

from flask import current_app
from flask_babel import lazy_gettext as _l
from mysql.connector import Error as MySQLError

from app.database import get_cursor, get_db
from app.extensions import bcrypt
from app.models import app_settings as app_settings_model
from app.models import role as role_model
from app.models import user as user_model

logger = logging.getLogger(__name__)

MODE_PERSONAL = 'single'
MODE_TEAM = 'multi'
MODES = (MODE_PERSONAL, MODE_TEAM)

KEY_MODE = 'deployment_mode'
KEY_REGISTRATION = 'allow_registration'
KEY_OWNER = 'owner_user_id'

OWNER_ROLE = 'admin'
PLACEHOLDER_EMAIL_DOMAIN = 'example.com'
PROVIDERS = ('openai', 'assemblyai', 'gemini', 'openrouter')
MIN_PASSWORD_LENGTH = 8

_cache: Dict[str, Any] = {'values': None, 'loaded_at': 0.0}


class AccessError(Exception):
    """A user-facing validation error. ``field`` names the form field, if any."""

    def __init__(self, message: str, field: Optional[str] = None, status: int = 400):
        super().__init__(message)
        self.message = message
        self.field = field
        self.status = status


# --- Settings storage -------------------------------------------------------

def invalidate_cache() -> None:
    _cache['values'] = None
    _cache['loaded_at'] = 0.0


def _load_settings() -> Tuple[Dict[str, Optional[str]], bool]:
    """Return (settings, ok). Cached for APP_SETTINGS_CACHE_SECONDS."""
    ttl = float(current_app.config.get('APP_SETTINGS_CACHE_SECONDS', 5))
    now = time.monotonic()
    cached = _cache['values']
    if cached is not None and ttl > 0 and now - _cache['loaded_at'] < ttl:
        return cached, True
    try:
        values = app_settings_model.get_all()
    except Exception as exc:  # DB down or table missing
        logger.warning("[Access] Could not load app settings: %s", exc)
        if cached is not None:
            return cached, True
        return {}, False
    _cache['values'] = values
    _cache['loaded_at'] = now
    return values, True


def _save(values: Dict[str, Optional[str]]) -> None:
    app_settings_model.set_values(values)
    invalidate_cache()


# --- Mode and locks ---------------------------------------------------------

def mode_locked() -> bool:
    return current_app.config.get('DEPLOYMENT_MODE') in MODES


def get_deployment_mode() -> str:
    configured = current_app.config.get('DEPLOYMENT_MODE')
    if configured in MODES:
        return configured
    values, ok = _load_settings()
    stored = values.get(KEY_MODE)
    if stored in MODES:
        return stored
    # Without a readable setting, fail closed: team mode requires sign-in.
    return MODE_PERSONAL if ok else MODE_TEAM


def is_team_mode() -> bool:
    return get_deployment_mode() == MODE_TEAM


def is_personal_mode() -> bool:
    return get_deployment_mode() == MODE_PERSONAL


def registration_locked() -> bool:
    return current_app.config.get('ALLOW_REGISTRATION') is not None


def registration_setting() -> bool:
    """The sign-up switch value, regardless of the current mode."""
    configured = current_app.config.get('ALLOW_REGISTRATION')
    if configured is not None:
        return bool(configured)
    values, _ok = _load_settings()
    return values.get(KEY_REGISTRATION) != '0'


def registration_allowed() -> bool:
    """Whether new accounts may be created (sign-up page, new Google users)."""
    return is_team_mode() and registration_setting()


def sign_in_locked() -> bool:
    """ADMIN_PASSWORD in the environment makes sign-in mandatory."""
    return bool(current_app.config.get('ADMIN_PASSWORD'))


# --- Owner ------------------------------------------------------------------

def get_owner_id() -> Optional[int]:
    values, _ok = _load_settings()
    raw = values.get(KEY_OWNER)
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


def get_owner():
    owner_id = get_owner_id()
    return user_model.get_user_by_id(owner_id) if owner_id else None


def is_owner(user) -> bool:
    owner_id = get_owner_id()
    return bool(user is not None and owner_id is not None and getattr(user, 'id', None) == owner_id)


def has_password(user) -> bool:
    return bool(user is not None and getattr(user, 'password_hash', None))


def owner_needs_no_sign_in(owner=None) -> bool:
    """True in open personal mode: the owner is signed in automatically."""
    if not is_personal_mode():
        return False
    owner = owner if owner is not None else get_owner()
    return owner is not None and not has_password(owner)


def user_allowed_in_current_mode(user) -> bool:
    """In personal mode only the owner may use the app."""
    if user is None:
        return False
    if is_team_mode():
        return True
    owner_id = get_owner_id()
    return owner_id is None or getattr(user, 'id', None) == owner_id


def _is_admin(user) -> bool:
    role = getattr(user, 'role', None) if user is not None else None
    return bool(role and getattr(role, 'access_admin_panel', False))


def can_access_admin_panel(user) -> bool:
    return is_team_mode() and _is_admin(user)


def can_manage_access(user) -> bool:
    """Who sees the Team mode section: the owner in personal mode, admins in team mode."""
    if user is None:
        return False
    if is_team_mode():
        return _is_admin(user)
    return is_owner(user)


def is_placeholder_email(email: Optional[str]) -> bool:
    return not email or str(email).lower().endswith('@' + PLACEHOLDER_EMAIL_DOMAIN)


def count_users() -> int:
    cursor = get_cursor()
    cursor.execute("SELECT COUNT(*) AS n FROM users")
    row = cursor.fetchone()
    return int(row['n']) if row else 0


def access_context(user) -> Dict[str, Any]:
    """Everything the templates need to render menus and the Access tab."""
    team = is_team_mode()
    owner = is_owner(user)
    open_mode = owner_needs_no_sign_in(user if owner else None) if user is not None else False
    context = {
        'team_mode': team,
        'mode_locked': mode_locked(),
        'is_owner': owner,
        'open_mode': open_mode,
        'has_password': has_password(user),
        'sign_in_locked': sign_in_locked(),
        'can_manage': can_manage_access(user),
        'can_access_admin': can_access_admin_panel(user),
        'registration_allowed': registration_setting(),
        'registration_locked': registration_locked(),
        'placeholder_email': is_placeholder_email(getattr(user, 'email', None)),
        'user_count': 0,
        'owner_id': get_owner_id(),
    }
    if context['can_manage'] and team:
        try:
            context['user_count'] = count_users()
        except Exception:
            logger.debug("[Access] Could not count users.", exc_info=True)
    return context


# --- API keys ---------------------------------------------------------------

def merge_env_provider_keys(status: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Mark providers with an environment key as available (personal mode)."""
    merged = dict(status or {})
    for provider in PROVIDERS:
        merged[provider] = bool(
            merged.get(provider) or current_app.config.get(f'{provider.upper()}_API_KEY')
        )
    return merged


# --- Validation helpers -----------------------------------------------------

def _hash(password: str) -> str:
    return bcrypt.generate_password_hash(
        password, current_app.config['BCRYPT_LOG_ROUNDS']
    ).decode('utf-8')


def _validate_new_password(password: Optional[str], confirm: Optional[str]) -> str:
    password = password or ''
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AccessError(_l('Password must be at least 8 characters long.'), field='password')
    if confirm is not None and password != confirm:
        raise AccessError(_l('Passwords do not match.'), field='confirm_password')
    return password


def _validate_username(user, username: Optional[str]) -> str:
    username = (username or '').strip()
    if not 4 <= len(username) <= 25:
        raise AccessError(_l('Username must be between 4 and 25 characters.'), field='username')
    existing = user_model.get_user_by_username(username)
    if existing and existing.id != user.id:
        raise AccessError(_l('That username is already taken.'), field='username')
    return username


def _validate_email(user, email: Optional[str], required: bool) -> Optional[str]:
    email = (email or '').strip()
    if not email:
        if required:
            raise AccessError(_l('Email is required for team mode (it is used for password resets).'), field='email')
        return None
    try:
        from email_validator import validate_email, EmailNotValidError
        email = validate_email(email, check_deliverability=False).normalized
    except EmailNotValidError:
        raise AccessError(_l('Please enter a valid email address.'), field='email')
    if is_placeholder_email(email) and required:
        raise AccessError(_l('Please enter your real email address.'), field='email')
    existing = user_model.get_user_by_email(email)
    if existing and existing.id != user.id:
        raise AccessError(_l('That email address is already used by another account.'), field='email')
    return email


def _require_current_password(user, current_password: Optional[str]) -> None:
    if not has_password(user) or not bcrypt.check_password_hash(user.password_hash, current_password or ''):
        raise AccessError(_l('Your current password is incorrect.'), field='current_password')


def _update_identity(user, username: Optional[str], email: Optional[str]) -> None:
    new_username = username or user.username
    new_email = email or user.email
    if new_username == user.username and new_email == user.email:
        return
    if not user_model.update_user_profile(user.id, new_username, new_email, user.first_name, user.last_name):
        raise AccessError(_l('Could not save your username or email. Please try again.'), status=500)


# --- Actions ----------------------------------------------------------------

def set_first_password(user, password: str, confirm: str,
                       username: Optional[str] = None, email: Optional[str] = None) -> None:
    """Give an account without a password its first password.

    For the personal-mode owner this turns sign-in on. Username and email
    are optional and only accepted from the owner.
    """
    if has_password(user):
        raise AccessError(_l('This account already has a password. Use Change Password instead.'))
    password = _validate_new_password(password, confirm)
    new_username = new_email = None
    if is_owner(user):
        if username is not None:
            new_username = _validate_username(user, username)
        new_email = _validate_email(user, email, required=False)
    _update_identity(user, new_username, new_email)
    if not user_model.update_user_password_hash(user.id, _hash(password)):
        raise AccessError(_l('Could not save your password. Please try again.'), status=500)
    logger.info("[Access] User %s set a first password.", user.id)


def remove_owner_password(user, current_password: str) -> None:
    """Turn sign-in off in personal mode."""
    if not is_personal_mode():
        raise AccessError(_l('Sign-in cannot be turned off in team mode.'), status=409)
    if not is_owner(user):
        raise AccessError(_l('Only the owner can change this.'), status=403)
    if sign_in_locked():
        raise AccessError(_l("Sign-in is required by your server's .env file (ADMIN_PASSWORD)."), status=409)
    _require_current_password(user, current_password)
    cursor = get_cursor()
    cursor.execute("UPDATE users SET password_hash = NULL WHERE id = %s", (user.id,))
    get_db().commit()
    logger.info("[Access] Owner %s turned sign-in off.", user.id)


def _ensure_admin_role(user) -> None:
    admin_role = role_model.get_role_by_name(OWNER_ROLE)
    if admin_role and user.role_id != admin_role.id:
        user_model.update_user_role(user.id, admin_role.id)


def enable_team_mode(user, allow_registration: bool, password: Optional[str] = None,
                     confirm: Optional[str] = None, username: Optional[str] = None,
                     email: Optional[str] = None) -> None:
    if mode_locked():
        raise AccessError(_l("The mode is set by DEPLOYMENT_MODE in your server's .env file."), status=409)
    if is_team_mode():
        raise AccessError(_l('Team mode is already on.'), status=409)
    if not is_owner(user):
        raise AccessError(_l('Only the owner can turn on team mode.'), status=403)

    needs_password = not has_password(user)
    if needs_password:
        password = _validate_new_password(password, confirm)
    new_username = _validate_username(user, username) if username is not None else None
    new_email = None
    if is_placeholder_email(user.email) or email:
        new_email = _validate_email(user, email, required=is_placeholder_email(user.email))

    _update_identity(user, new_username, new_email)
    if needs_password and not user_model.update_user_password_hash(user.id, _hash(password)):
        raise AccessError(_l('Could not save your password. Please try again.'), status=500)
    _ensure_admin_role(user)
    values = {KEY_MODE: MODE_TEAM, KEY_OWNER: str(user.id)}
    if not registration_locked():
        values[KEY_REGISTRATION] = '1' if allow_registration else '0'
    _save(values)
    logger.info("[Access] User %s turned on team mode (sign-ups: %s).", user.id, registration_setting())


def disable_team_mode(user, current_password: str) -> None:
    if mode_locked():
        raise AccessError(_l("The mode is set by DEPLOYMENT_MODE in your server's .env file."), status=409)
    if not is_team_mode():
        raise AccessError(_l('Team mode is already off.'), status=409)
    if not _is_admin(user):
        raise AccessError(_l('Only an admin can switch back to personal mode.'), status=403)
    if not has_password(user):
        raise AccessError(_l('Set a password first: Google sign-in is turned off in personal mode.'),
                          field='current_password')
    _require_current_password(user, current_password)
    _save({KEY_MODE: MODE_PERSONAL, KEY_OWNER: str(user.id)})
    logger.info("[Access] User %s switched back to personal mode and is now the owner.", user.id)


def set_registration_allowed(user, allowed: bool) -> None:
    if registration_locked():
        raise AccessError(_l("Sign-ups are set by ALLOW_REGISTRATION in your server's .env file."), status=409)
    if not is_team_mode() or not _is_admin(user):
        raise AccessError(_l('Only an admin can change sign-ups in team mode.'), status=403)
    _save({KEY_REGISTRATION: '1' if allowed else '0'})
    logger.info("[Access] User %s set sign-ups to %s.", user.id, allowed)


def reset_owner_password(new_password: str) -> str:
    """CLI recovery: set the owner's password. Returns the owner's username."""
    owner = get_owner()
    if owner is None:
        raise AccessError(_l('No owner account found. Run `flask bootstrap` first.'))
    password = _validate_new_password(new_password, None)
    if not user_model.update_user_password_hash(owner.id, _hash(password)):
        raise AccessError(_l('Could not save the password.'), status=500)
    return owner.username


# --- Startup ----------------------------------------------------------------

def _find_existing_owner(stored_id: Optional[str]):
    if stored_id:
        try:
            user = user_model.get_user_by_id(int(stored_id))
            if user:
                return user
        except (TypeError, ValueError):
            pass
    admin_username = current_app.config.get('ADMIN_USERNAME')
    if admin_username:
        user = user_model.get_user_by_username(admin_username)
        if user:
            return user
    cursor = get_cursor()
    cursor.execute(
        """
        SELECT u.id FROM users u JOIN roles r ON r.id = u.role_id
        WHERE r.access_admin_panel = 1 ORDER BY u.id LIMIT 1
        """
    )
    row = cursor.fetchone()
    cursor.fetchall()
    if not row:
        cursor.execute("SELECT id FROM users ORDER BY id LIMIT 1")
        row = cursor.fetchone()
        cursor.fetchall()
    return user_model.get_user_by_id(row['id']) if row else None


def _create_owner(mode: str):
    from app.services import user_service

    username = current_app.config.get('ADMIN_USERNAME') or 'admin'
    email = current_app.config.get('ADMIN_EMAIL') or f'{username}@{PLACEHOLDER_EMAIL_DOMAIN}'
    password = current_app.config.get('ADMIN_PASSWORD')
    if mode == MODE_TEAM and not password:
        raise RuntimeError(
            'Team mode (DEPLOYMENT_MODE=multi) needs a first admin, but ADMIN_PASSWORD is not set. '
            'Set ADMIN_USERNAME and ADMIN_PASSWORD in your .env file, or remove DEPLOYMENT_MODE to '
            'start in personal mode.'
        )
    if not role_model.get_role_by_name(OWNER_ROLE):
        raise RuntimeError(f"Role '{OWNER_ROLE}' not found. Run `flask create-roles` first.")
    owner = user_model.add_user(username, email, _hash(password) if password else None, OWNER_ROLE)
    if not owner:
        raise RuntimeError(f"Could not create the owner account '{username}'.")
    get_db().commit()
    user_service.handle_new_user_template_sync(owner.id)
    logger.info("[Access] Created owner account '%s' (sign-in %s).", username, 'on' if password else 'off')
    return owner


def ensure_access_settings() -> None:
    """Idempotent startup step: settings table, stored mode, owner account.

    Existing databases with users default to team mode so upgrading never
    switches a team installation to personal mode.
    """
    app_settings_model.init_db_command()
    invalidate_cache()
    stored = app_settings_model.get_all()
    if stored.get(KEY_MODE) not in MODES:
        mode = MODE_TEAM if count_users() > 0 else MODE_PERSONAL
        app_settings_model.set_values({KEY_MODE: mode})
        logger.info("[Access] Stored initial mode '%s'.", mode)
    invalidate_cache()

    mode = get_deployment_mode()
    owner = _find_existing_owner(stored.get(KEY_OWNER))
    if owner is None:
        owner = _create_owner(mode)
    if str(owner.id) != str(stored.get(KEY_OWNER) or ''):
        app_settings_model.set_values({KEY_OWNER: str(owner.id)})

    env_password = current_app.config.get('ADMIN_PASSWORD')
    if env_password and not has_password(owner):
        user_model.update_user_password_hash(owner.id, _hash(env_password))
        owner = user_model.get_user_by_id(owner.id)
        logger.info("[Access] Applied ADMIN_PASSWORD to the owner account.")

    if mode == MODE_PERSONAL and not _is_admin(owner):
        # The owner is the only usable account in personal mode; give it every permission.
        _ensure_admin_role(owner)

    if mode == MODE_TEAM and not has_password(owner) and not owner.oauth_provider:
        raise RuntimeError(
            'Team mode is on but the owner account has no password, so nobody could sign in. '
            'Set ADMIN_PASSWORD in your .env file.'
        )
    invalidate_cache()
