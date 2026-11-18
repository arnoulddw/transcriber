# app/services/auth_service.py
# Handles user authentication, registration, and password verification logic.

import logging
from flask import current_app, session
from app.logging_config import get_logger
from typing import Optional, Dict, Any
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import cachecontrol
import requests

from app.extensions import bcrypt
from app.models import user as user_model
from app.models.user import User
from app.models import role as role_model
from app.services import user_service

from mysql.connector import Error as MySQLError

class AuthServiceError(Exception):
    """Custom exception for authentication service errors."""
    pass

class InvalidCredentialsError(AuthServiceError):
    """Exception for invalid current password during change."""
    pass


_google_session = None

def _get_google_session():
    """Creates a cached HTTP session for Google requests."""
    global _google_session
    if _google_session is None:
        _google_session = cachecontrol.CacheControl(requests.session())
    return _google_session

def create_user(username: str, password: str, email: str, role_name: str = 'beta-tester', language: Optional[str] = None) -> Optional[User]:
    """
    Creates a new user with a hashed password and assigns a role by name.
    Handles password hashing using Flask-Bcrypt. Now uses MySQL backend via models.

    Args:
        username: The desired username.
        password: The plain text password.
        email: The user's email address.
        role_name: The name of the role to assign (defaults to 'beta-tester').
        language: The user's preferred UI language.

    Returns:
        The created User object or None if creation failed.

    Raises:
        AuthServiceError: If role validation fails or username/email is taken.
        ValueError: If username, password, or email is empty.
    """
    logger = get_logger(__name__, component="Auth")
    if not username or not password or not email:
        logger.error("Attempted to create user with empty username, password, or email.")
        raise ValueError("Username, password, and email cannot be empty.")

    try:
        logger.info("Creating user.", extra={"role": role_name})
        role = role_model.get_role_by_name(role_name)
        if not role:
            logger.error(f"Cannot create user: Role '{role_name}' not found.")
            raise AuthServiceError(f"Cannot create user: Role '{role_name}' does not exist.")
        logger.debug("Role found.", extra={"role_id": role.id, "role": role.name})

        existing_user_by_name = user_model.get_user_by_username(username)
        if existing_user_by_name:
            logger.warning("Attempted to create user with duplicate username.")
            raise AuthServiceError(f"Username '{username}' is already taken.")
        existing_user_by_email = user_model.get_user_by_email(email)
        if existing_user_by_email:
            logger.warning("Attempted to create user with duplicate email.")
            raise AuthServiceError(f"Email address '{email}' is already registered.")

        hashed_password = bcrypt.generate_password_hash(
            password, current_app.config['BCRYPT_LOG_ROUNDS']
        ).decode('utf-8')
        logger.debug("Password hashed.")

        new_user = user_model.add_user(username, email, hashed_password, role_name, language)

        if new_user:
            from app.database import get_db
            db = get_db()
            db.commit()
            logger.info("User created successfully.", extra={"role": role_name})
            user_service.handle_new_user_template_sync(new_user.id)
            return new_user
        else:
            logger.error("Failed to create user (model returned None).")
            raise AuthServiceError("Failed to save user to database.")

    except AuthServiceError as ase:
        raise ase
    except MySQLError as db_err:
        logger.error(f"Database error creating user: {db_err}", exc_info=True)
        raise AuthServiceError(f"A database error occurred during user creation.") from db_err
    except Exception as e:
        logger.error(f"Unexpected error creating user: {e}", exc_info=True)
        raise AuthServiceError(f"An unexpected error occurred during user creation: {e}") from e


def verify_password(username: str, password_provided: str) -> Optional[User]:
    """
    Verifies a user's provided password against the stored hash. Uses MySQL backend via models.

    Args:
        username: The username attempting to log in.
        password_provided: The plain text password provided.

    Returns:
        The User object if authentication is successful, None otherwise.
    """
    logger = get_logger(__name__, component="Auth")
    if not username or not password_provided:
        logger.warning("Verify password called with empty username or password.")
        return None

    try:
        user = user_model.get_user_by_username(username)

        if user and user.password_hash:
            if bcrypt.check_password_hash(user.password_hash, password_provided):
                logger.info("Password verification successful.")
                return user
            else:
                logger.warning("Password verification failed: incorrect password.")
                return None
        elif user and not user.password_hash:
            logger.warning("Login attempt failed: user has no password set (likely OAuth user).")
            return None
        else:
            logger.warning("User not found during password verification.")
            return None
    except MySQLError as db_err:
        logger.error(f"Database error during password verification: {db_err}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Error during password verification: {e}", exc_info=True)
        return None


def verify_google_id_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verifies the Google ID token and returns the user info payload if valid.

    Args:
        token: The ID token string received from the frontend.

    Returns:
        A dictionary containing user info (sub, email, name, etc.) or None if invalid.

    Raises:
        AuthServiceError: If verification fails due to configuration or other issues.
    """
    logger = get_logger(__name__, component="Auth:Google")
    if not token:
        logger.warning("Received empty Google ID token.")
        return None

    google_client_id = current_app.config.get('GOOGLE_CLIENT_ID')
    if not google_client_id:
        logger.error("GOOGLE_CLIENT_ID is not configured. Cannot verify token.")
        raise AuthServiceError("Google Sign-In is not configured on the server.")

    try:
        request_session = _get_google_session()
        idinfo = id_token.verify_oauth2_token(token, google_requests.Request(session=request_session), google_client_id)
        logger.info("Google ID token verified successfully.")
        return idinfo

    except ValueError as e:
        logger.error(f"Google ID token verification failed: {e}", exc_info=True)
        raise AuthServiceError(f"Invalid Google Sign-In token: {e}") from e
    except Exception as e:
        logger.error(f"Unexpected error verifying Google ID token: {e}", exc_info=True)
        raise AuthServiceError("An unexpected error occurred during Google Sign-In verification.") from e


def handle_google_login(idinfo: Dict[str, Any], allow_create: bool = True) -> Optional[User]:
    """
    Handles user login/registration based on verified Google ID token info.
    Finds existing user by Google ID or email, or creates a new user.

    Args:
        idinfo: The dictionary of claims from the verified Google ID token.

    Returns:
        The User object (existing or newly created) or None on failure.

    Raises:
        AuthServiceError: If user creation/linking fails.
    """
    logger = get_logger(__name__, component="Auth:Google")
    provider = 'google'
    provider_id = idinfo.get('sub')
    email = idinfo.get('email')
    first_name = idinfo.get('given_name')
    last_name = idinfo.get('family_name')

    if not provider_id or not email:
        logger.error("Missing 'sub' (Google ID) or 'email' in verified token payload.")
        raise AuthServiceError("Incomplete user information received from Google.")

    try:
        user = user_model.get_user_by_oauth(provider, provider_id)
        if user:
            logger.info("Found existing user via Google ID.", extra={"found_user_id": user.id})
            return user

        user = user_model.get_user_by_email(email)
        if user:
            logger.info("Found existing user via email; linking Google ID.", extra={"found_user_id": user.id})
            success = user_model.link_oauth_to_user(user.id, provider, provider_id)
            if not success:
                raise AuthServiceError(f"Failed to link Google account to existing user {user.id}.")
            return user

        if not allow_create:
            logger.info("No existing user found and sign-ups are turned off; refusing Google sign-in.")
            raise AuthServiceError("Sign-ups are turned off. Ask an admin to create an account for you.")
        logger.info("No existing user found; creating new OAuth user.")
        language_from_session = session.get('language')
        if language_from_session:
            logger.debug("Language found in session for new OAuth user.", extra={"language": language_from_session})

        new_user = user_model.add_oauth_user(
            email=email,
            first_name=first_name,
            last_name=last_name,
            oauth_provider=provider,
            oauth_provider_id=provider_id,
            language=language_from_session
        )
        if not new_user:
            logger.error("Failed to create new user via add_oauth_user.")
            raise AuthServiceError("Failed to create new user account after Google Sign-In.")

        logger.info("New user created via Google Sign-In.", extra={"new_user_id": new_user.id})
        user_service.handle_new_user_template_sync(new_user.id)
        return new_user

    except MySQLError as db_err:
        logger.error(f"Database error during Google login handling: {db_err}", exc_info=True)
        raise AuthServiceError("A database error occurred during Google Sign-In.") from db_err
    except Exception as e:
        logger.error(f"Unexpected error during Google login handling: {e}", exc_info=True)
        if isinstance(e, AuthServiceError):
            raise e
        else:
            raise AuthServiceError("An unexpected error occurred during Google Sign-In.") from e


_logger = get_logger(__name__, component="Auth")

def get_user_by_username(username: str) -> Optional[User]:
    """Retrieves a user by username (simple wrapper around model function using MySQL)."""
    try:
        return user_model.get_user_by_username(username)
    except MySQLError as db_err:
        _logger.error(f"DB error in get_user_by_username: {db_err}", exc_info=True)
        return None
    except Exception as e:
        _logger.error(f"Error in get_user_by_username: {e}", exc_info=True)
        return None

def get_user_by_email(email: str) -> Optional[User]:
    """Retrieves a user by email address (simple wrapper around model function using MySQL)."""
    try:
        return user_model.get_user_by_email(email)
    except MySQLError as db_err:
        _logger.error(f"DB error in get_user_by_email: {db_err}", exc_info=True)
        return None
    except Exception as e:
        _logger.error(f"Error in get_user_by_email: {e}", exc_info=True)
        return None

def get_user_by_id(user_id: int) -> Optional[User]:
    """Retrieves a user by ID (simple wrapper around model function using MySQL)."""
    try:
        return user_model.get_user_by_id(user_id)
    except MySQLError as db_err:
        _logger.error(f"DB error in get_user_by_id: {db_err}", exc_info=True)
        return None
    except Exception as e:
        _logger.error(f"Error in get_user_by_id: {e}", exc_info=True)
        return None

def _get_serializer() -> URLSafeTimedSerializer:
    """Creates a serializer instance using the app's secret key."""
    secret_key = current_app.config.get('SECRET_KEY')
    if not secret_key:
        raise AuthServiceError("SECRET_KEY is not configured, cannot generate tokens.")
    return URLSafeTimedSerializer(secret_key, salt='password-reset-salt')

def generate_password_reset_token(user_id: int) -> str:
    """Generates a secure, time-limited token for password reset."""
    logger = get_logger(__name__, user_id=user_id, component="Auth:Token")
    try:
        s = _get_serializer()
        token = s.dumps(user_id)
        logger.info("Generated password reset token.")
        return token
    except Exception as e:
        logger.error(f"Failed to generate password reset token: {e}", exc_info=True)
        raise AuthServiceError("Could not generate password reset token.") from e

def verify_password_reset_token(token: str) -> Optional[int]:
    """Verifies a password reset token and returns the user ID if valid."""
    logger = get_logger(__name__, component="Auth:Token")
    try:
        s = _get_serializer()
        max_age_seconds = current_app.config['PASSWORD_RESET_TOKEN_MAX_AGE_SECONDS']
        user_id = s.loads(token, max_age=max_age_seconds)
        logger.info("Password reset token verified.", extra={"verified_user_id": user_id})
        return user_id
    except SignatureExpired:
        logger.warning("Password reset token expired.")
        return None
    except BadSignature:
        logger.warning("Invalid password reset token signature.")
        return None
    except Exception as e:
        logger.error(f"Error verifying password reset token: {e}", exc_info=True)
        return None

def reset_user_password(user_id: int, new_password: str) -> bool:
    """Resets the user's password after verifying a reset token. Uses MySQL backend via models."""
    logger = get_logger(__name__, user_id=user_id, component="Auth:ResetPwd")
    if not new_password or len(new_password) < 8:
        logger.warning("Password reset failed: password too short.")
        raise ValueError("New password must be at least 8 characters long.")

    try:
        hashed_password = bcrypt.generate_password_hash(
            new_password, current_app.config['BCRYPT_LOG_ROUNDS']
        ).decode('utf-8')
        logger.debug("New password hashed.")

        success = user_model.update_user_password_hash(user_id, hashed_password)

        if success:
            logger.info("Password reset successfully.")
            return True
        else:
            logger.error("Failed to update password hash in database (model returned False).")
            raise AuthServiceError("Failed to update password in database.")

    except MySQLError as db_err:
        logger.error(f"Database error during password reset: {db_err}", exc_info=True)
        raise AuthServiceError("A database error occurred during password reset.") from db_err
    except Exception as e:
        logger.error(f"Error during password reset: {e}", exc_info=True)
        if isinstance(e, (ValueError, AuthServiceError)):
            raise e
        else:
            raise AuthServiceError("An unexpected error occurred during password reset.") from e


def change_password(user_id: int, current_password: str, new_password: str) -> None:
    """
    Changes the password for an authenticated user.

    Args:
        user_id: The ID of the user changing their password.
        current_password: The user's current password for verification.
        new_password: The desired new password.

    Raises:
        InvalidCredentialsError: If the current password is incorrect.
        ValueError: If the new password is too short.
        AuthServiceError: For database or unexpected errors.
    """
    logger = get_logger(__name__, user_id=user_id, component="Auth:ChangePwd")
    logger.info("Password change request received.")

    user = get_user_by_id(user_id)
    if not user:
        logger.error("User not found during password change attempt.")
        raise AuthServiceError("User not found.")
    if not user.password_hash:
        logger.warning("Password change attempt failed: user has no password set (likely OAuth).")
        raise AuthServiceError("Password change is not available for this account type.")

    if not verify_password(user.username, current_password):
        logger.warning("Password change failed: incorrect current password.")
        raise InvalidCredentialsError("Incorrect current password.")

    if not new_password or len(new_password) < 8:
        logger.warning("Password change failed: new password too short.")
        raise ValueError("New password must be at least 8 characters long.")

    try:
        success = reset_user_password(user_id, new_password)
        if not success:
            raise AuthServiceError("Failed to update password in database.")
        logger.info("Password changed successfully.")
    except (ValueError, AuthServiceError) as e:
        logger.error(f"Error during password update step: {e}")
        raise e
    except Exception as e:
        logger.error(f"Unexpected error during password update step: {e}", exc_info=True)
        raise AuthServiceError("An unexpected error occurred while changing the password.") from e

def is_admin(user: Optional[User]) -> bool:
    """
    Checks if a given user object has administrative privileges.
    Currently checks if the user's role has the 'access_admin_panel' permission.
    """
    is_admin_user = False
    if user and user.is_authenticated and user.role:
        is_admin_user = user.role.access_admin_panel

    _logger.debug("Admin check.", extra={"is_admin": is_admin_user})
    return is_admin_user