# tests/functional/conftest.py

import pytest
import json

# Standard test models registered into the catalog by clean_db. Models only
# exist in the catalog after an admin/user saves an API key, so functional
# tests that transcribe with a fixed api_choice must mirror that by
# registering the rows (register_model_from_provider is exactly what
# save_user_api_key calls).
TEST_CATALOG_MODELS = [
    ("openai", "gpt-4o-transcribe", "OpenAI GPT-4o Transcribe", "transcription"),
    ("openai", "gpt-transcribe", "OpenAI GPT Transcribe", "transcription"),
    ("assemblyai", "universal", "AssemblyAI Universal", "transcription"),
    # NOTE: no bare "openrouter" row — OpenRouter is a provider, not a model;
    # tests that need OpenRouter mock get_active_models with slug entries.
]


def _register_test_catalog_models() -> None:
    """Register the standard test models into the transcription catalog.

    Mirrors the production key-save flow (save_user_api_key →
    register_model_from_provider) so permission checks and dropdowns in
    functional tests resolve like they do for a configured instance.
    """
    try:
        from app.models import transcription_catalog as catalog_model
        for provider, code, display_name, purpose in TEST_CATALOG_MODELS:
            catalog_model.register_model_from_provider(
                provider=provider,
                code=code,
                display_name=display_name,
                model_purpose=purpose,
            )
    except Exception as exc:  # pragma: no cover - diagnostic only
        import logging
        logging.getLogger(__name__).warning(
            "Failed to register test catalog models: %s", exc
        )


@pytest.fixture(scope='function')
def clean_db(app):
    """Truncate all tables in the test database and reset auto-increment."""
    with app.app_context():
        from app.database import get_db
        from app.models.role import invalidate_role_cache
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        cursor.execute("TRUNCATE TABLE app_settings")
        cursor.execute("TRUNCATE TABLE user_prompts")
        cursor.execute("TRUNCATE TABLE template_prompts")
        cursor.execute("TRUNCATE TABLE llm_operations")
        cursor.execute("TRUNCATE TABLE background_jobs")
        cursor.execute("TRUNCATE TABLE live_transcription_sessions")
        cursor.execute("TRUNCATE TABLE transcriptions")
        cursor.execute("TRUNCATE TABLE user_usage")
        cursor.execute("TRUNCATE TABLE public_api_keys")
        cursor.execute("TRUNCATE TABLE user_api_keys")
        cursor.execute("TRUNCATE TABLE users")
        cursor.execute("TRUNCATE TABLE roles")
        # Reset centralized catalog tables to ensure consistent test state
        cursor.execute("TRUNCATE TABLE transcription_models_catalog")
        cursor.execute("TRUNCATE TABLE transcription_languages_catalog")
        # Register the standard test models, mimicking what happens when an
        # admin saves API keys (models enter the catalog via key-save only).
        _register_test_catalog_models()
        # Explicitly reset auto-increment to ensure fresh IDs
        cursor.execute("ALTER TABLE roles AUTO_INCREMENT = 1")
        cursor.execute("ALTER TABLE users AUTO_INCREMENT = 1")
        cursor.execute("ALTER TABLE public_api_keys AUTO_INCREMENT = 1")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        conn.commit()
        cursor.close()
        # Invalidate in-memory role cache so stale entries from previous tests
        # don't cause ID collisions after AUTO_INCREMENT reset.
        invalidate_role_cache()
        from app.services import access_service
        access_service.invalidate_cache()

@pytest.fixture(scope='function')
def logged_in_client(app, clean_db):
    """A test client that is logged in with a clean database."""
    with app.test_client() as client:
        with app.app_context():
            from app.services import auth_service
            from app.models import role as role_model
            # Create a test user and role
            if not role_model.get_role_by_name('test_role'):
                role_model.create_role('test_role', 'A role for testing')
            if not auth_service.get_user_by_username('testuser'):
                auth_service.create_user('testuser', 'testpassword', 'test@example.com', 'test_role')

        # Log in the test user
        client.post('/login', data=json.dumps({
            'username': 'testuser',
            'password': 'testpassword'
        }), content_type='application/json', headers={'Accept': 'application/json'})

        yield client

@pytest.fixture(scope='function')
def logged_in_client_with_permissions(app, clean_db):
    """A test client that is logged in with a clean database and a role with all permissions."""
    import logging
    from unittest.mock import _patch
    logger = logging.getLogger(__name__)
    
    # Stop any active patches that might interfere (from previous tests)
    patches_stopped = 0
    for patch_obj in list(_patch._active_patches):
        try:
            patch_obj.stop()
            patches_stopped += 1
        except:
            pass
    
    if patches_stopped > 0:
        logger.warning(f"FIXTURE: Stopped {patches_stopped} lingering patches from previous tests")
    
    with app.test_client() as client:
        with app.app_context():
            from app.services import auth_service
            from app.models import role as role_model
            from app.models import user as user_model
            from app.database import get_db
            from flask_login import current_user
            
            logger.info("=" * 80)
            logger.info("FIXTURE: logged_in_client_with_permissions - START")
            logger.info("=" * 80)

            if not getattr(app, "_test_workflow_permission_hook", False):
                @app.before_request
                def _grant_permissions():
                    if current_user.is_authenticated and current_user.role:
                        current_user.role.allow_workflows = True
                        current_user.role.manage_workflow_templates = True
                        current_user.role.allow_auto_title_generation = True
                        current_user.role.allow_speaker_diarization = True
                app._test_workflow_permission_hook = True
            
            # Verify clean state - no roles should exist after clean_db
            existing_roles = role_model.get_all_roles()
            logger.info(f"FIXTURE: Checking database state - found {len(existing_roles)} existing roles")
            if existing_roles:
                logger.warning(f"FIXTURE: Found {len(existing_roles)} existing roles after clean_db: {[(r.id, r.name, r.use_api_openai_whisper) for r in existing_roles]}")
                # Force clean the roles table again
                cursor = get_db().cursor()
                cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
                cursor.execute("TRUNCATE TABLE roles")
                cursor.execute("ALTER TABLE roles AUTO_INCREMENT = 1")
                cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
                get_db().commit()
                cursor.close()
                logger.info("FIXTURE: Forced roles table cleanup")
            else:
                logger.info("FIXTURE: Database is clean - no existing roles")
            
            # Always create a fresh role with correct permissions (clean_db has truncated roles table)
            logger.info("FIXTURE: Creating admin role with all permissions")
            permissions = {
                'use_api_assemblyai': True,
                'allow_workflows': True,
                'use_api_openai_whisper': True,
                'use_api_openai_gpt_4o_transcribe': True,
                'use_api_openai_live_transcribe': True,
                'use_api_google_gemini': True,
                'use_api_openrouter': True,
                'allow_api_key_management': True,
                'allow_public_api_access': True,
                'allow_auto_title_generation': True,
                'allow_speaker_diarization': True,
                'allow_download_transcript': True,
                'access_admin_panel': True,
                'allow_large_files': True,
                'allow_context_prompt': True,
            }
            role = role_model.create_role('admin', 'Administrator role for tests', permissions)
            if not role:
                raise RuntimeError("Failed to create admin role for tests")
            logger.info(f"FIXTURE: Created role - id={role.id}, name={role.name}, allow_workflows={role.allow_workflows}")

            # Create the test user
            logger.info("FIXTURE: Creating testuser_permissions")
            auth_service.create_user('testuser_permissions', 'password123', 'test_permissions@example.com', role.name)
            
            # Enable auto-title generation for the test user
            user = user_model.get_user_by_username('testuser_permissions')
            if not user:
                raise RuntimeError("Failed to create testuser_permissions")
                
            logger.info(f"FIXTURE: Found user - id={user.id}, username={user.username}, role_id={user.role_id}, enable_auto_title={user.enable_auto_title_generation}")
            
            # Enable auto-title generation
            logger.info(f"FIXTURE: Enabling auto-title generation for user {user.id}")
            user_model.update_user_preferences(user.id, None, None, True, None)
            
            # Verify the setup (avoid accessing user.role as it may trigger lingering mocks)
            user_after = user_model.get_user_by_id(user.id)
            logger.info(f"FIXTURE: After updates - user_id={user_after.id}, role_id={user_after.role_id}, enable_auto_title={user_after.enable_auto_title_generation}")
            
            # Verify role directly from database instead of through user.role property
            role_check = role_model.get_role_by_id(user_after.role_id)
            if role_check:
                logger.info(f"FIXTURE: User role verified from DB - role_name={role_check.name}, use_api_openai_whisper={role_check.use_api_openai_whisper}, allow_auto_title_generation={role_check.allow_auto_title_generation}")
            else:
                logger.warning(f"FIXTURE: Could not load role with ID {user_after.role_id} from database!")
            
            logger.info("FIXTURE: logged_in_client_with_permissions - SETUP COMPLETE")

        # Log in the test user
        client.post('/login', data=json.dumps({
            'username': 'testuser_permissions',
            'password': 'password123'
        }), content_type='application/json', headers={'Accept': 'application/json'})

        yield client
@pytest.fixture(scope='function')
def app():
    """Create and configure a new app instance for each test session."""
    from app import create_app
    import app.database as database
    from tests.functional.config.test_config import TestConfig

    # Ensure a fresh DB pool per test to avoid cross-app leakage
    database.db_pool = None
    app = create_app(config_class=TestConfig)
    app.config['PASSWORD_RESET_TOKEN_MAX_AGE_SECONDS'] = 3600

    with app.app_context():
        from app.initialization import initialize_database_schema, create_initialization_marker
        from app.database import get_db
        
        # Drop all tables first to ensure clean state
        cursor = get_db().cursor()
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        cursor.execute("DROP TABLE IF EXISTS app_settings, user_prompts, template_prompts, llm_operations, background_jobs, live_transcription_sessions, transcription_job_leases, transcriptions, user_usage, public_api_keys, user_api_keys, users, roles;")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        get_db().commit()
        
        # Manually run the necessary initialization for the test environment
        initialize_database_schema(create_roles=False)
        
        # Manually create the marker file to signal that initialization is complete
        create_initialization_marker(app.config)

    yield app

    with app.app_context():
        from app.database import get_db
        from app.models.role import invalidate_role_cache
        from app.services.admin_metrics_service import invalidate_metrics_cache
        cursor = get_db().cursor()
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        cursor.execute("DROP TABLE IF EXISTS app_settings, user_prompts, template_prompts, llm_operations, background_jobs, live_transcription_sessions, transcription_job_leases, transcriptions, user_usage, public_api_keys, user_api_keys, users, roles;")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        get_db().commit()
        # Clear in-memory caches to prevent bleed into the next test's app instance.
        invalidate_role_cache()
        invalidate_metrics_cache()
        from app.database import close_db
        close_db()
        # Reset the global DB pool after each test to prevent config leakage
        import app.database as database
        database.db_pool = None
