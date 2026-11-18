# app/api/auth.py
# Defines the Blueprint for authentication routes (login, logout, register).
# Handles both HTML page rendering and form submissions.

import logging
from app.logging_config import get_logger
from flask import (
    Blueprint, request, jsonify, flash, redirect, url_for, render_template,
    current_app, session
)
from flask_login import login_user, logout_user, login_required, current_user
from flask_wtf.csrf import generate_csrf
# Removed: from werkzeug.urls import url_parse
# Add this if needed later for redirect validation within this blueprint:
from urllib.parse import urlparse
# --- NEW: Import gettext for translation ---
from flask_babel import gettext as _, lazy_gettext as _l

# Import extensions and application components
from app.extensions import limiter, csrf # Import limiter instance and CSRF extension
from app.forms import LoginForm, RegistrationForm, ForgotPasswordForm, ResetPasswordForm
from app.services import auth_service, email_service
from app.services.auth_service import AuthServiceError # Specific exception
from app.models import user as user_model
from app.services import access_service

# Define the Blueprint
# No url_prefix here, routes like /login, /register are defined directly
auth_bp = Blueprint('auth', __name__)

# --- Rate Limiting ---
# Apply specific (stricter) limits to authentication endpoints
# Limit by a combination of IP address AND username (if submitted) to prevent brute-force
# on specific accounts while still limiting overall attempts from an IP.
def auth_limit_key():
    # Use username from form OR json payload OR fallback to remote IP
    username = None
    if request.form:
        username = request.form.get('username')
    elif request.is_json:
        username = request.json.get('username')
    # Combine IP and username (if available) for a more specific key
    key = f"{request.remote_addr or 'unknown'}"
    if username:
        key += f":{username}"
    return key

limit_auth_attempts = "10 per minute;100 per hour"
limit_reset_attempts = "5 per hour" # Limit password reset requests
limit_oauth_attempts = "20 per minute;200 per hour" # Limit OAuth callbacks

# --- HTML Routes for Login/Register Pages ---

@auth_bp.route('/api/csrf-token', methods=['GET'])
def csrf_token():
    """Return a fresh CSRF token for long-lived pages before retrying AJAX requests."""
    if not current_user.is_authenticated:
        return jsonify({'error': _('Authentication required.')}), 401

    response = jsonify({'csrf_token': generate_csrf()})
    response.headers.update({
        'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
        'Pragma': 'no-cache',
        'Expires': '0',
    })
    return response


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit(limit_auth_attempts, key_func=auth_limit_key)
def login():
    """Handles user login page (GET) and form submission (POST)."""
    # Redirect if user is already authenticated
    if current_user.is_authenticated:
        return redirect(url_for('main.index')) # Redirect to main index page

    form = LoginForm()
    if form.validate_on_submit(): # Handles POST validation and CSRF
        username = form.username.data
        password = form.password.data
        remember = form.remember_me.data
        logger = get_logger(__name__, component="Auth:Login")
        logger.info("Login attempt received.")

        try:
            user = auth_service.verify_password(username, password)
            if user and not access_service.user_allowed_in_current_mode(user):
                logger.warning("Login refused: personal mode allows only the owner.", extra={"refused_user_id": user.id})
                flash(_l('Transcriber is in personal mode, so only its owner can sign in.'), 'danger')
                user = None
                return render_template('login.html', title='Login', form=form)
            if user:
                login_user(user, remember=remember)
                logger.info("Login successful.", extra={"logged_in_user_id": user.id})
                flash(_l('Logged in successfully'), 'success')

                # --- NEW: Persist language from session to profile ---
                if 'language' in session:
                    lang_to_set = session['language']
                    logger.debug("Persisting language from session to user profile.", extra={"language": lang_to_set})
                    try:
                        user_model.update_user_preferences(user.id, default_language=None, default_model=None, language=lang_to_set)
                        session.pop('language', None)
                    except Exception as e:
                        logger.error(f"Failed to persist language preference from session: {e}", exc_info=True)
                # --- END NEW ---

                next_page = request.args.get('next')
                target_url = url_for('main.index')
                if next_page:
                    parsed_next = urlparse(next_page)
                    if parsed_next.netloc == '' or parsed_next.netloc == request.host:
                        target_url = next_page
                    else:
                        logger.warning("Invalid 'next' parameter detected; redirecting home.", extra={"next": next_page})

                return redirect(target_url)
            else:
                flash(_l('Invalid username or password.'), 'danger')
                logger.warning("Login failed: invalid credentials.")

        except Exception as e:
            logger.error(f"Unexpected error during login: {e}", exc_info=True)
            flash(_l('An unexpected error occurred during login. Please try again.'), 'danger')

    # Render the login page for GET requests or failed POST validation
    # Pass google_client_id from config via context processor
    return render_template('login.html', title='Login', form=form)


@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit(limit_auth_attempts) # Limit registration attempts by IP
def register():
    """Handles user registration page (GET) and form submission (POST)."""
    # Sign-ups need team mode with sign-ups turned on.
    if not access_service.registration_allowed():
        flash(_l('Sign-ups are turned off. Ask an admin to create an account for you.'), 'warning')
        return redirect(url_for('auth.login'))

    # Redirect if user is already authenticated
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    form = RegistrationForm()
    if form.validate_on_submit(): # Handles POST validation and CSRF
        username = form.username.data
        password = form.password.data
        email = form.email.data
        logger = get_logger(__name__, component="Auth:Register")
        logger.info("Registration attempt received.")

        try:
            # --- NEW: Get language from session ---
            language_from_session = session.get('language')
            if language_from_session:
                logger.debug("Language found in session for new user.", extra={"language": language_from_session})
            # --- END NEW ---

            new_user = auth_service.create_user(username, password, email, language=language_from_session)
            if new_user:
                # --- NEW: Pop language from session after successful registration ---
                if language_from_session:
                    session.pop('language', None)
                # --- END NEW ---
                logger.info("Registration successful.", extra={"new_user_id": new_user.id})
                flash(_l('Account created for %(username)s! You can now log in.', username=username), 'success')
                return redirect(url_for('auth.login'))
            else:
                flash(_l('Registration failed. Please try again.'), 'danger')

        except AuthServiceError as ase:
            logger.warning(f"Registration failed: {ase}")
            flash(str(ase), 'danger')
        except Exception as e:
            logger.error(f"Unexpected error during registration: {e}", exc_info=True)
            flash(_l('An unexpected error occurred during registration. Please try again.'), 'danger')
            return redirect(url_for('auth.register'))

    # Render the registration page for GET requests or failed POST validation
    # Pass google_client_id from config via context processor
    return render_template('login.html', title='Register', form=form)


@auth_bp.route('/logout', methods=['POST'])
@login_required # User must be logged in to log out
def logout():
    """Logs the current user out."""
    user_id = current_user.id
    logout_user()
    get_logger(__name__, user_id=user_id, component="Auth:Logout").info("User logged out.")
    flash(_l('You have been logged out successfully.'), 'success')
    return redirect(url_for('auth.login')) # Redirect to login page


# --- Password Reset Routes ---

@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit(limit_reset_attempts) # Limit reset requests by IP
def forgot_password():
    """Handles the 'Forgot Password' request page and form submission."""
    if current_user.is_authenticated:
        return redirect(url_for('main.index')) # No need if already logged in
    if not access_service.is_team_mode():
        flash(_l('Password reset by email is only available in team mode.'), 'warning')
        return redirect(url_for('auth.login'))

    form = ForgotPasswordForm()
    if form.validate_on_submit():
        email = form.email.data
        logger = get_logger(__name__, component="Auth:ForgotPwd")
        logger.info("Forgot password request received.")
        try:
            user = auth_service.get_user_by_email(email)
            if user:
                token = auth_service.generate_password_reset_token(user.id)
                if all(current_app.config.get(key) for key in ['MAIL_SERVER', 'MAIL_USERNAME', 'MAIL_PASSWORD', 'MAIL_DEFAULT_SENDER']):
                    email_service.send_password_reset_email(user.email, user.username, token)
                    logger.info("Password reset email sent.", extra={"found_user_id": user.id})
                else:
                    logger.error("Email service not configured. Cannot send reset email.")
            else:
                logger.debug("Forgot password request for non-existent email (not disclosed to client).")

            flash(_l('If an account with that email exists, a password reset link has been sent. Please check your inbox and spam folder if you don\'t see it within a few minutes.'), 'info')
            return redirect(url_for('auth.login'))

        except Exception as e:
            logger.error(f"Error processing forgot password request: {e}", exc_info=True)
            flash(_l('An error occurred while processing your request. Please try again.'), 'danger')
            return redirect(url_for('auth.login'))

    return render_template('forgot_password.html', title='Forgot Password', form=form)


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
@limiter.limit(limit_reset_attempts) # Limit reset attempts by IP (token is part of URL)
def reset_password_request(token):
    """Handles the password reset link verification (GET) and new password submission (POST)."""
    if current_user.is_authenticated:
        return redirect(url_for('main.index')) # No need if already logged in
    if not access_service.is_team_mode():
        flash(_l('Password reset by email is only available in team mode.'), 'warning')
        return redirect(url_for('auth.login'))

    logger = get_logger(__name__, component="Auth:ResetPwd")

    user_id = auth_service.verify_password_reset_token(token)
    if not user_id:
        logger.warning("Invalid or expired password reset token.")
        flash(_l('The password reset link is invalid or has expired.'), 'danger')
        return redirect(url_for('auth.forgot_password'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        new_password = form.password.data
        logger.info("Valid token. Attempting password reset.", extra={"reset_user_id": user_id})
        try:
            success = auth_service.reset_user_password(user_id, new_password)
            if success:
                logger.info("Password reset successful.", extra={"reset_user_id": user_id})
                flash(_l('Your password has been reset successfully. You can now log in.'), 'success')
                return redirect(url_for('auth.login'))
            else:
                flash(_l('Password reset failed. Please try again.'), 'danger')
        except Exception as e:
            logger.error(f"Error resetting password: {e}", exc_info=True, extra={"reset_user_id": user_id})
            flash(_l('An error occurred while resetting your password. Please try again.'), 'danger')
            return redirect(url_for('auth.forgot_password'))

    logger.debug("Valid token. Displaying reset password form.", extra={"reset_user_id": user_id})
    return render_template('reset_password.html', title='Reset Password', form=form, token=token)


# --- Google Sign-In Callback --- # <<< NEW ROUTE

@auth_bp.route('/api/auth/google-callback', methods=['POST'])
@csrf.exempt # Google posts the ID token directly, so skip default CSRF validation
@limiter.limit(limit_oauth_attempts) # Apply rate limiting
def google_callback():
    """Handles the callback from Google Sign-In (receives ID token)."""
    logger = get_logger(__name__, component="Auth:GoogleCallback")
    if current_user.is_authenticated:
        logger.warning("Received callback while user already logged in.", extra={"current_user_id": current_user.id})
        return jsonify({'success': True, 'message': _('Already logged in.'), 'redirect': url_for('main.index')})

    if not access_service.is_team_mode():
        logger.warning("Google Sign-In attempted outside team mode.")
        return jsonify({'success': False, 'error': _('Google Sign-In is only available in team mode.')}), 403

    if not current_app.config.get('GOOGLE_CLIENT_ID'):
        logger.error("Attempted Google Sign-In callback, but GOOGLE_CLIENT_ID is not configured.")
        return jsonify({'success': False, 'error': _('Google Sign-In is not configured on the server.')}), 500

    # Get the ID token from the request payload (Google may post JSON or form data)
    id_token_str = None
    payload_source = None
    if request.is_json:
        data = request.get_json(silent=True) or {}
        id_token_str = data.get('id_token') or data.get('credential')
        payload_source = 'json' if id_token_str else None
    if not id_token_str and request.form:
        id_token_str = request.form.get('id_token') or request.form.get('credential')
        payload_source = payload_source or 'form'

    if not id_token_str:
        logger.error("Invalid request: missing ID token.", extra={"content_type": request.content_type, "payload_source": payload_source})
        return jsonify({'success': False, 'error': _('Invalid request payload.')}), 400

    try:
        idinfo = auth_service.verify_google_id_token(id_token_str)
        if not idinfo:
            return jsonify({'success': False, 'error': _('Invalid Google token.')}), 401

        user = auth_service.handle_google_login(idinfo, allow_create=access_service.registration_allowed())
        if not user:
            return jsonify({'success': False, 'error': _('Failed to process Google Sign-In.')}), 500

        # --- NEW: Persist language from session to profile ---
        if 'language' in session:
            lang_to_set = session['language']
            logger.debug("Persisting language from session for Google login.", extra={"language": lang_to_set})
            try:
                user_model.update_user_preferences(user.id, default_language=None, default_model=None, language=lang_to_set)
                session.pop('language', None)
            except Exception as e:
                logger.error(f"Failed to persist language preference from session: {e}", exc_info=True)
        # --- END NEW ---

        login_user(user, remember=True)
        logger.info("User logged in via Google.", extra={"logged_in_user_id": user.id})

        next_page = request.args.get('next')
        redirect_url = url_for('main.index')

        if next_page:
            parsed_next = urlparse(next_page)
            if parsed_next.netloc == '' or parsed_next.netloc == request.host:
                redirect_url = next_page
            else:
                logger.warning("Invalid 'next' parameter during OAuth callback; redirecting home.", extra={"next": next_page})

        wants_json = (
            request.is_json
            or request.accept_mimetypes.best == 'application/json'
            or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        )

        if wants_json:
            return jsonify({'success': True, 'message': _('Login successful.'), 'redirect': redirect_url}), 200

        return redirect(redirect_url)

    except AuthServiceError as e:
        logger.error(f"Authentication service error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Unexpected error during Google callback: {e}", exc_info=True)
        return jsonify({'success': False, 'error': _('An unexpected server error occurred.')}), 500


# --- Optional: JSON API Endpoints (If needed for JS-driven auth) ---
# @auth_bp.route('/api/login', methods=['POST'])
# @limiter.limit(limit_auth_attempts, key_func=auth_limit_key)
# def api_login(): ...

# @auth_bp.route('/api/register', methods=['POST'])
# @limiter.limit(limit_auth_attempts)
# def api_register(): ...

# @auth_bp.route('/api/logout', methods=['POST'])
# @login_required
# def api_logout(): ...
