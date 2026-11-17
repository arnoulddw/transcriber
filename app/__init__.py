# app/__init__.py

import os
import logging
import fcntl # For file locking
import decimal
import secrets
from datetime import datetime, timezone
from dateutil.parser import isoparse
from typing import Optional, Mapping, Any
from urllib.parse import urlparse
from flask import Flask, render_template, g, request, jsonify, redirect, url_for, flash, current_app, session
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import BadRequest

# Import Flask-Login current_user proxy
from flask_login import current_user
# --- NEW: Import get_locale and gettext ---
from flask_babel import get_locale, gettext as _, lazy_gettext as _l
from babel.numbers import format_currency as babel_format_currency, format_decimal, format_percent as babel_format_percent

# Import extensions, config, blueprints, and other components
from app.config import Config
from app.extensions import bcrypt, login_manager, csrf, limiter, mail, babel
from app.database import init_app as init_db
# Import models and services needed for initialization and user loading
from app.models import role as role_model
from app.models import user as user_model
from app.models import transcription as transcription_model, llm_operation as llm_operation_model
from app.models.user import User
from app.models.role import Role
from app.services import user_service, auth_service
from app.services.auth_service import AuthServiceError
# --- Import new initialization functions ---
from app.initialization import (
    check_initialization_marker,
    create_initialization_marker,
    run_initialization_sequence
)
from app.logging_config import setup_logging, get_logger
from app.cli import register_cli_commands
# Import MySQL error class for specific handling if needed later
from mysql.connector import Error as MySQLError


# --- One-time Initialization Management (Using File Lock) ---
_resources_initialized_in_process = False
_file_lock_handle = None

def initialize_app_resources(app: Flask):
    """
    Handles one-time application initialization (DB, roles, admin) if it is
    explicitly invoked by an operator or startup process.
    Uses a non-blocking file lock (fcntl.flock) to ensure only one process succeeds.
    """
    global _resources_initialized_in_process, _file_lock_handle
    logger = get_logger(__name__, component="System:Init")

    is_main_process_or_prod = not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true'

    if not is_main_process_or_prod:
        logger.debug("Skipping resource initialization in Flask debug reloader sub-process.")
        return

    if _resources_initialized_in_process:
        logger.debug("Application resources already initialized in this process. Skipping.")
        return

    lock_file_path = app.config.get('TASK_LOCK_FILE')
    if not lock_file_path:
        logger.error("TASK_LOCK_FILE not configured. Cannot initialize resources safely.")
        return

    logger.debug(f"Attempting to acquire file lock: {lock_file_path}")

    try:
        runtime_dir = os.path.dirname(lock_file_path)
        os.makedirs(runtime_dir, exist_ok=True)

        _file_lock_handle = open(lock_file_path, 'a')
        fcntl.flock(_file_lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        logger.debug("File lock acquired.")
        initialization_done = False
        try:
            with app.app_context():
                if not check_initialization_marker(app.config):
                    logger.debug("Initialization marker not found. Running initialization sequence...")
                    run_initialization_sequence(app)
                    create_initialization_marker(app.config)
                    initialization_done = True
                    logger.info("Initialization sequence completed and marker created.")
                else:
                    logger.debug("Initialization marker found. Skipping initialization sequence.")
                    initialization_done = True

            if initialization_done:
                _resources_initialized_in_process = True
                logger.debug("Application resource initialization completed.")
            else:
                logger.error("Initialization sequence failed. Background tasks will NOT start.")
                fcntl.flock(_file_lock_handle.fileno(), fcntl.LOCK_UN)
                _file_lock_handle.close()
                _file_lock_handle = None

        except Exception as e:
            logger.critical(f"CRITICAL ERROR during initialization or task startup after acquiring lock: {e}", exc_info=True)
            try:
                fcntl.flock(_file_lock_handle.fileno(), fcntl.LOCK_UN)
                _file_lock_handle.close()
                _file_lock_handle = None
            except Exception as lock_release_err:
                logger.error(f"Failed to release lock after error: {lock_release_err}")

    except BlockingIOError:
        logger.debug("File lock already held by another process. Skipping resource initialization.")
        if _file_lock_handle:
            _file_lock_handle.close()
            _file_lock_handle = None
    except Exception as e:
        logger.error(f"Error acquiring file lock: {e}", exc_info=True)
        if _file_lock_handle:
            try: _file_lock_handle.close()
            except Exception: pass
            _file_lock_handle = None

# --- Timezone Formatting Filter ---
def format_datetime_tz(value, format=None): # format arg is now ignored
    """
    Jinja filter to parse a datetime string/object and convert it to a
    standardized UTC ISO 8601 string, ready for client-side processing.
    """
    if not value:
        return ""
    try:
        if isinstance(value, str):
            dt_object = isoparse(value)
        elif isinstance(value, datetime):
            dt_object = value
        else:
            return "Invalid Date Type"

        # Ensure the datetime object is timezone-aware (assume UTC if naive)
        if dt_object.tzinfo is None:
            dt_object = dt_object.replace(tzinfo=timezone.utc)

        # Convert to UTC and format as ISO 8601 string with 'Z' for UTC
        return dt_object.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    except (ValueError, TypeError) as e:
        logging.error(f"Could not parse or format datetime '{value}': {e}")
        return "Invalid Date"

# --- Contrast Color Filter ---
def get_contrast_color(hex_color: Optional[str]) -> str:
    """
    Jinja filter to determine if black or white text provides better contrast
    against a given background hex color.
    """
    if not hex_color or not hex_color.startswith('#') or len(hex_color) != 7:
        return 'black'
    try:
        hex_val = hex_color.lstrip('#')
        rgb = tuple(int(hex_val[i:i+2], 16) for i in (0, 2, 4))
        luminance = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255
        return 'black' if luminance > 0.5 else 'white'
    except Exception as e:
        logging.error(f"Error calculating contrast color for '{hex_color}': {e}")
        return 'black'


# --- Raw Number Filter (for JS data attributes) ---
def raw_number_filter(value):
    """Jinja filter to ensure a number is output in a raw, machine-readable format."""
    if value is None:
        return '0'
    # This will format Decimals correctly as strings without trailing zeros
    if isinstance(value, decimal.Decimal):
        return format(value, 'f')
    return str(value)


# --- Application Factory ---
def create_app(config_class=Config) -> Flask:
    """
    Creates and configures the Flask application instance.
    """
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.config.from_object(config_class)
    setup_logging(app.config)

    def _should_emit_startup_banner() -> bool:
        runtime_dir = app.config.get('RUNTIME_DIR')
        parent_pid = os.getppid()
        flag_filename = f".startup_logged_{parent_pid}"
        if not runtime_dir:
            return True
        flag_path = os.path.join(runtime_dir, flag_filename)
        try:
            os.makedirs(runtime_dir, exist_ok=True)
            with open(flag_path, 'x', encoding='utf-8') as flag_file:
                flag_file.write(str(os.getpid()))
            return True
        except FileExistsError:
            logging.debug("[SYSTEM] Startup banner already emitted for parent process %s; suppressing duplicate log.", parent_pid)
            return False
        except OSError as err:
            logging.warning("[SYSTEM] Could not manage startup banner flag at %s (%s); emitting log anyway.", flag_path, err)
            return True

    _sys_logger = get_logger(__name__, component="System")
    if _should_emit_startup_banner():
        _sys_logger.info("Flask app created.", extra={"deployment_mode": app.config['DEPLOYMENT_MODE'], "timezone": app.config.get('TZ', 'UTC')})

    # --- MODIFIED: Define locale selector function before initializing Babel ---
    def get_locale_selector():
        # This selector should prioritize the user's explicit choice for UI language.
        # 1. Get language from user's profile if available
        if hasattr(g, 'user') and g.user and g.user.is_authenticated and g.user.language:
            return g.user.language
        # 2. Otherwise, get language from session
        try:
            if 'language' in session:
                return session.get('language')
        except RuntimeError:
            # Fallback for CLI commands or background tasks
            pass
        # 3. Otherwise, get language from browser's accept languages (for anonymous users)
        try:
            return request.accept_languages.best_match(current_app.config['SUPPORTED_LANGUAGES'])
        except RuntimeError:
            return current_app.config['SUPPORTED_LANGUAGES'][0]

    def get_timezone_selector():
        if g.user and g.user.is_authenticated and g.user.timezone:
            return g.user.timezone
        return 'UTC' # Default timezone

    # Initialize Flask Extensions
    bcrypt.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    limiter.storage_uri = app.config['RATELIMIT_STORAGE_URI']
    limiter.default_limits = app.config['RATELIMIT_DEFAULT'].split(';')
    mail.init_app(app)
    # --- MODIFIED: Initialize Babel with the selector function ---
    babel.init_app(app, locale_selector=get_locale_selector, timezone_selector=get_timezone_selector)
    _sys_logger.debug("Flask extensions initialized (Bcrypt, LoginManager, CSRF, Limiter, Mail, Babel).")

    # Initialize Database Handling
    init_db(app)

    # Register Jinja Filters
    app.jinja_env.filters['datetime_tz'] = format_datetime_tz
    app.jinja_env.filters['contrast_color'] = get_contrast_color
    app.jinja_env.filters['raw_number'] = raw_number_filter

    def custom_format_currency(number, currency, locale):
        """Custom currency formatter to ensure '$' is used for USD."""
        logging.debug(f"Formatting currency for {number} with locale {locale}")
        # \xa0 is a non-breaking space, which Babel might use.
        formatted_str = babel_format_currency(number, currency, locale=locale)
        return formatted_str.replace('US', '')

    app.jinja_env.globals['format_currency'] = custom_format_currency
    app.jinja_env.globals['format_number'] = format_decimal
    
    def custom_format_percent(value: Any, locale: Optional[str] = None) -> str:
        """Format percent values that may be provided either as 0-1 ratios or 0-100 percents."""
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            numeric_value = 0.0

        normalized_value = numeric_value / 100.0 if abs(numeric_value) > 1 else numeric_value
        if locale:
            return babel_format_percent(normalized_value, locale=locale)
        return babel_format_percent(normalized_value)

    app.jinja_env.globals['format_percent'] = custom_format_percent
    _sys_logger.debug("Registered Jinja filters and globals.")

    # Configure Flask-Login User Loader
    @login_manager.user_loader
    def load_user(user_id_str: str) -> Optional[User]:
        try:
            user_id = int(user_id_str)
            _loader_logger = get_logger(__name__, user_id=user_id, component="Auth:UserLoader")
            user = user_model.get_user_by_id(user_id)
            if user: _loader_logger.debug("User loaded successfully.")
            else: _loader_logger.warning("User not found in database.")
            return user
        except ValueError:
            get_logger(__name__, component="Auth:UserLoader").warning(f"Invalid user_id format received: {user_id_str}")
            return None
        except Exception as e:
            _loader_logger = get_logger(__name__, component="Auth:UserLoader")
            if isinstance(e, MySQLError): _loader_logger.error(f"MySQL error loading user {user_id_str}: {e}", exc_info=True)
            else: _loader_logger.error(f"Error loading user {user_id_str}: {e}", exc_info=True)
            return None

    # Register Blueprints
    from app.main import main_bp
    from app.api.auth import auth_bp
    from app.api.transcriptions import transcriptions_bp
    from app.api.user_settings import user_settings_bp
    from app.api.admin import admin_bp
    from app.admin_panel import admin_panel_bp
    from app.api.workflows import workflows_bp
    from app.api.llm import llm_bp
    from app.api.live import live_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(transcriptions_bp)
    app.register_blueprint(user_settings_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(admin_panel_bp)
    app.register_blueprint(workflows_bp)
    app.register_blueprint(llm_bp)
    app.register_blueprint(live_bp)
    _sys_logger.debug("Blueprints registered.")


    # Register Request Hooks
    @app.before_request
    def before_request_func():
        g.csp_nonce = secrets.token_urlsafe(24)
        g.user = current_user if current_user.is_authenticated else None
        g.role = g.user.role if g.user else None
        _req_logger = get_logger(__name__, component="Request")
        user_info = f"User:{current_user.id}" if current_user.is_authenticated else "Anonymous"
        _req_logger.debug(f"Request started: {request.method} {request.path} from {request.remote_addr} ({user_info})")

        if current_app.testing:
            _req_logger.debug("Bypassing initialization gate in testing mode.")
            g.initialization_complete = True
        else:
            g.initialization_complete = False
            try:
                if 'INIT_MARKER_FILE' in current_app.config:
                    g.initialization_complete = check_initialization_marker()
                else:
                    _req_logger.debug("Skipping initialization check: INIT_MARKER_FILE not in config.")
                    g.initialization_complete = False
            except Exception as init_check_err:
                _req_logger.error(f"Error checking initialization marker during request: {init_check_err}")

        allowed_endpoints = ['static', 'auth.login', 'auth.register', 'auth.forgot_password', 'auth.reset_password_request', 'auth.google_callback', 'main.set_language']
        if (not g.initialization_complete and
                request.endpoint and
                request.endpoint not in allowed_endpoints and
                not request.endpoint.startswith('static')):
            _req_logger.warning(f"Initialization pending. Blocking request to {request.endpoint}. Returning 503.")
            return jsonify({'error': _('Service temporarily unavailable. Initialization in progress.')}), 503

        if (app.config['DEPLOYMENT_MODE'] == 'multi' and
                not current_user.is_authenticated and
                request.endpoint and
                not request.endpoint.startswith('static') and
                request.endpoint not in allowed_endpoints):
            if request.path.startswith(('/api/v1/transcribe', '/api/v1/transcriptions')):
                auth_header = request.headers.get('Authorization', '')
                if auth_header and auth_header.lower().startswith('bearer '):
                    _req_logger.debug("Allowing public API token flow for public transcription endpoint.")
                    return None
            is_api_request = request.path.startswith('/api/') or \
                             ('Accept' in request.headers and 'application/json' in request.headers['Accept'])
            if is_api_request:
                _req_logger.warning(f"Unauthorized API access attempt: {request.method} {request.path}")
                return jsonify({'error': _('Authentication required.')}), 401
            else:
                _req_logger.debug(f"Redirecting unauthenticated user to login. Endpoint: {request.endpoint}")
                flash(_l("Please log in to access this page."), "info")
                return redirect(url_for('auth.login', next=request.url))

    @app.after_request
    def after_request_func(response):
        user_info = f"User:{current_user.id}" if current_user.is_authenticated else "Anonymous"
        get_logger(__name__, component="Request").debug(f"Request finished: {request.method} {request.path} - {response.status_code} ({user_info})")
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        csp_nonce = getattr(g, 'csp_nonce', '')
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{csp_nonce}' https://accounts.google.com https://apis.google.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https://cdn.jsdelivr.net wss://generativelanguage.googleapis.com; "
            "frame-src https://accounts.google.com; "
            "object-src 'none';"
        )
        if app.config.get('DEPLOYMENT_MODE') == 'multi':
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    # Register Context Processors
    @app.context_processor
    def inject_global_vars():
        user: Optional[User] = current_user if current_user.is_authenticated else None
        role: Optional[Role] = user.role if user else None
        is_multi = app.config['DEPLOYMENT_MODE'] == 'multi'
        initial_key_status = {}
        user_permissions = {}
        from app.models import transcription_catalog as transcription_catalog_model
        from app.models import llm_catalog as llm_catalog_model

        _ctx_logger = get_logger(__name__, component="Context")
        try:
            catalog_models = transcription_catalog_model.get_active_models()
        except Exception as catalog_err:
            _ctx_logger.error(f"Failed to load transcription models from catalog: {catalog_err}", exc_info=True)
            catalog_models = []

        try:
            supported_languages = transcription_catalog_model.get_language_map()
        except Exception as lang_err:
            _ctx_logger.error(f"Failed to load transcription languages from catalog: {lang_err}", exc_info=True)
            supported_languages = app.config.get('SUPPORTED_LANGUAGE_NAMES', {})

        try:
            llm_model_catalog = llm_catalog_model.get_active_models()
        except Exception as llm_catalog_err:
            _ctx_logger.error(f"Failed to load LLM models from catalog: {llm_catalog_err}", exc_info=True)
            llm_model_catalog = []

        supported_ui_languages = app.config.get('SUPPORTED_LANGUAGES', [])

        api_name_map_for_frontend_subset = {}
        for model in catalog_models:
            code = str(model.get('code') or '').strip()
            model_key = str(model.get('model_key') or code).strip()
            display_name = model.get('display_name')
            if model_key:
                api_name_map_for_frontend_subset[model_key] = display_name
            if code:
                # Keep the bare alias for historical transcript metadata and
                # older browser state while new selectors use model_key.
                api_name_map_for_frontend_subset.setdefault(code, display_name)

        def _update_live_model_context(entries):
            for live_entry in entries:
                code = str(live_entry.get('code') or '').strip()
                model_key = str(live_entry.get('model_key') or code).strip()
                display_name = live_entry.get('display_name')
                if model_key:
                    api_name_map_for_frontend_subset[model_key] = display_name
                if code:
                    # Keep the bare alias for historical transcript metadata
                    # and older browser state.
                    api_name_map_for_frontend_subset.setdefault(code, display_name)

        live_transcription_models = transcription_catalog_model.get_live_models(initial_key_status)
        _update_live_model_context(live_transcription_models)

        color_name_map = {
            "#ffffff": "Default", "#ffd1dc": "Pink", "#aec6cf": "Blue Grey",
            "#cfffd1": "Mint Green", "#fffacd": "Lemon", "#e6e6fa": "Lavender",
            "#ffb347": "Orange"
        }

        if is_multi and user:
            try:
                initial_key_status = user_service.get_effective_key_status(user)
            except Exception as e:
                _ctx_logger.error(f"Error fetching initial key status: {e}", exc_info=True)
            if role:
                user_permissions = {
                    'use_api_openai': role.use_api_openai,
                    'use_api_assemblyai': role.use_api_assemblyai,
                    'use_api_google': role.use_api_google,
                    'use_api_openai_whisper': role.use_api_openai_whisper,
                    'use_api_openai_gpt_4o_transcribe': role.use_api_openai_gpt_4o_transcribe,
                    'use_api_openai_live_transcribe': role.use_api_openai_live_transcribe,
                    'use_api_google_gemini': role.use_api_google_gemini,
                    'use_api_openrouter': role.use_api_openrouter,
                    'allow_large_files': role.allow_large_files,
                    'allow_context_prompt': role.allow_context_prompt,
                    'allow_download_transcript': role.allow_download_transcript,
                    'allow_api_key_management': role.allow_api_key_management,
                    'allow_public_api_access': getattr(role, 'allow_public_api_access', False),
                    'access_admin_panel': role.access_admin_panel,
                    'allow_workflows': role.allow_workflows,
                    'manage_workflow_templates': role.manage_workflow_templates,
                    'allow_auto_title_generation': role.allow_auto_title_generation,
                    'allow_speaker_diarization': role.allow_speaker_diarization
                }

            live_transcription_models = transcription_catalog_model.get_live_models(initial_key_status)
            _update_live_model_context(live_transcription_models)
        elif not is_multi:
             initial_key_status = {
                 'openai': bool(app.config.get('OPENAI_API_KEY')),
                 'assemblyai': bool(app.config.get('ASSEMBLYAI_API_KEY')),
                 'gemini': bool(app.config.get('GEMINI_API_KEY')),
                 'openrouter': bool(app.config.get('OPENROUTER_API_KEY'))
             }
             user_permissions = {
                 'use_api_openai': True, 'use_api_google': True,
                 'use_api_assemblyai': True, 'use_api_openai_whisper': True,
                 'use_api_openai_gpt_4o_transcribe': True, 'use_api_openai_live_transcribe': True,
                 'use_api_google_gemini': True,
                 'use_api_openrouter': True,
                 'allow_large_files': True, 'allow_context_prompt': True,
                 'allow_download_transcript': True, 'allow_api_key_management': False,
                 'allow_public_api_access': True,
                 'access_admin_panel': False, 'allow_workflows': True,
                 'manage_workflow_templates': False, 'allow_auto_title_generation': True,
                 'allow_speaker_diarization': True
             }

        if not is_multi:
            live_transcription_models = transcription_catalog_model.get_live_models(initial_key_status)
            _update_live_model_context(live_transcription_models)

        if user or not is_multi:
            # ``initial_key_status`` already contains the admin-configured
            # models shared with users who cannot manage their own keys.
            effective_key_status = dict(initial_key_status)
            for service in ('openai', 'assemblyai', 'gemini', 'openrouter'):
                effective_key_status[service] = bool(
                    effective_key_status.get(service)
                    or app.config.get(f'{service.upper()}_API_KEY')
                )
            llm_model_catalog = llm_catalog_model.filter_models_by_api_key_status(
                llm_model_catalog,
                effective_key_status,
                allow_provider_wide=not is_multi,
            )

        available_transcription_models = transcription_catalog_model.build_model_options(
            catalog_models,
            initial_key_status,
        )

        display_name = user.first_name if user and user.first_name else user.username if user else None

        # --- MODIFIED: Determine UI language and Formatting locale separately ---
        ui_locale = get_locale()
        
        # Determine the best locale for number formatting from the browser
        accept_langs = request.accept_languages
        formatting_locale_str = None
        
        # Custom logic for Belgian locales
        for lang, quality in accept_langs:
            lang_lower = lang.lower()
            if 'be' in lang_lower:
                if lang_lower.startswith('fr'):
                    formatting_locale_str = 'fr'
                    break
                if lang_lower.startswith('nl'):
                    formatting_locale_str = 'nl'
                    break
        
        if not formatting_locale_str:
            formatting_locale_str = accept_langs.best_match(current_app.config['SUPPORTED_LANGUAGES'])

        if not formatting_locale_str:
            formatting_locale_str = ui_locale.language
        # --- END MODIFIED ---

        return dict(
            csp_nonce=getattr(g, 'csp_nonce', ''),
            compass_branding=bool(app.config.get('COMPASS_BRANDING')),
            app_name='Compass Platform' if app.config.get('COMPASS_BRANDING') else 'Transcriber',
            deployment_mode=app.config['DEPLOYMENT_MODE'],
            is_multi_user=is_multi,
            current_user=user,
            current_role=role,
            display_name=display_name,
            now=datetime.now(timezone.utc),
            initial_key_status=initial_key_status,
            transcription_models=available_transcription_models,
            user_permissions=user_permissions,
            google_client_id=app.config.get('GOOGLE_CLIENT_ID'),

            supported_languages=supported_languages,
            SUPPORTED_UI_LANGS_CONFIG=supported_ui_languages,
            API_NAME_MAP_FRONTEND=api_name_map_for_frontend_subset,
            TRANSCRIPTION_MODEL_CATALOG=available_transcription_models,
            live_transcription_models=live_transcription_models,
            LIVE_TRANSCRIPTION_MODELS=live_transcription_models,
            LLM_MODEL_CATALOG=llm_model_catalog,
            COLOR_NAME_MAP=color_name_map,
            app_debug=app.debug,
            # --- MODIFIED: Provide both UI language and formatting locale ---
            current_language=ui_locale.language,
            formatting_locale=formatting_locale_str,
            # --- END MODIFIED ---
            build_timestamp=app.config.get('BUILD_TIMESTAMP')
        )

    # Register Error Handlers
    _err_logger = get_logger(__name__, component="ErrorHandler")

    @app.errorhandler(404)
    def not_found_error(error):
        _err_logger.warning(f"404 Not Found: {request.path}", extra={"referer": request.referrer, "user_id": current_user.id if current_user.is_authenticated else None})
        if request.path.startswith('/api/'): return jsonify({'error': _('Not Found')}), 404
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        original_exception = getattr(error, "original_exception", error)
        _err_logger.error(f"500 Internal Server Error: {request.path}", exc_info=original_exception, extra={"user_id": current_user.id if current_user.is_authenticated else None})
        try:
            db_conn = getattr(g, 'db_conn', None)
            if db_conn:
                _err_logger.debug("Attempting rollback due to 500 error.")
                db_conn.rollback()
                _err_logger.debug("Rollback successful.")
        except MySQLError as db_err: _err_logger.error(f"MySQL error during rollback in 500 handler: {db_err}")
        except Exception as db_err: _err_logger.error(f"Error during rollback in 500 handler: {db_err}")
        if request.path.startswith('/api/'): return jsonify({'error': _('Internal Server Error')}), 500
        return render_template('errors/500.html'), 500

    @app.errorhandler(403)
    def forbidden_error(error):
        _err_logger.warning(f"403 Forbidden: {request.path}", extra={"reason": error.description, "user_id": current_user.id if current_user.is_authenticated else None})
        if request.path.startswith('/api/'): return jsonify({'error': _('Forbidden'), 'message': error.description}), 403
        flash(error.description or _l("You do not have permission to access this page."), "danger")
        return render_template('errors/403.html'), 403

    @app.errorhandler(401)
    def unauthorized_error(error):
        _err_logger.warning(f"401 Unauthorized: {request.path}", extra={"reason": error.description, "user_id": current_user.id if current_user.is_authenticated else None})
        if request.path.startswith('/api/'): return jsonify({'error': _('Unauthorized'), 'message': error.description or _('Authentication required.')}), 401
        else: flash(error.description or _l("Authentication required to access this page."), "warning"); return redirect(url_for('auth.login', next=request.url))

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        _err_logger.warning(
            "400 CSRF failure: %s",
            request.path,
            extra={
                "reason": error.description,
                "content_type": request.content_type,
                "content_length": request.content_length,
                "user_id": current_user.id if current_user.is_authenticated else None,
            },
        )
        if request.path.startswith('/api/'):
            return jsonify({
                'error': _('Your session security token expired or was invalid. Please refresh the page and try again.'),
                'code': 'CSRF_TOKEN_INVALID',
            }), 400
        flash(_l("Your session expired. Please refresh the page and try again."), "warning")
        return redirect(url_for('main.index'))

    @app.errorhandler(400)
    def bad_request_error(error):
        description = getattr(error, "description", None) or str(error)
        _err_logger.warning(
            "400 Bad Request: %s",
            request.path,
            extra={
                "reason": description,
                "content_type": request.content_type,
                "content_length": request.content_length,
                "user_id": current_user.id if current_user.is_authenticated else None,
            },
        )
        if request.path.startswith('/api/'):
            message = _('The request could not be understood. Please refresh the page and try again.')
            if isinstance(error, BadRequest) and description:
                message = f"{message} {_('Details')}: {description}"
            return jsonify({'error': message, 'code': 'BAD_REQUEST'}), 400
        return render_template('errors/500.html'), 400

    @app.errorhandler(429)
    def ratelimit_handler(e):
        g.user = current_user if current_user.is_authenticated else None
        _err_logger.warning(f"Rate limit exceeded at {request.path}", extra={"client_ip": request.remote_addr, "description": e.description})
        if request.path.startswith('/api/'):
            api_error_message = _('Too many requests. Please wait a moment and try again.')
            description_text = (e.description or "").strip()
            if description_text:
                api_error_message = f"{api_error_message} {_('Details')}: {description_text}"
            return jsonify({'error': api_error_message, 'code': 'RATE_LIMIT_EXCEEDED'}), 429
        else:
            flash(_l("Too many requests: %(description)s. Please try again later.", description=e.description), "warning")
            referrer = request.referrer; target_url = url_for('main.index')
            try:
                if referrer and urlparse(referrer).netloc == urlparse(request.url_root).netloc: target_url = referrer
            except Exception: pass
            return redirect(target_url)

    @app.errorhandler(413)
    def payload_too_large_error(error):
        _err_logger.warning(f"413 Payload Too Large: {request.path}", extra={"content_length": request.content_length, "user_id": current_user.id if current_user.is_authenticated else None})
        max_size_bytes = current_app.config.get('MAX_CONTENT_LENGTH', 0)
        max_size_mb = round(max_size_bytes / (1024*1024))
        error_message = _('File is too large. The maximum allowed file size is %(size)sMB.', size=max_size_mb)
        return jsonify({'error': error_message, 'code': 'SIZE_LIMIT_EXCEEDED'}), 413


    # --- MODIFIED: REMOVED automatic initialization call ---
    # Initialization is now handled by the test runner or a production startup script.
    # initialize_app_resources(app)

    # --- MODIFIED: REMOVED old locale selector definition ---

    register_cli_commands(app)
    _sys_logger.info("Application initialization complete.")
    return app
