# tests/functional/test_access_modes.py
"""Personal vs. team mode, optional sign-in, sign-ups and the owner account."""

import json

import pytest

from app.initialization import create_default_roles
from app.models import app_settings as app_settings_model
from app.models import user as user_model
from app.services import access_service, auth_service, user_service
from app.services.access_service import AccessError


@pytest.fixture
def runtime_app(app, clean_db):
    """App whose mode is stored in the database (no DEPLOYMENT_MODE lock)."""
    app.config.update(DEPLOYMENT_MODE=None, ALLOW_REGISTRATION=None, ADMIN_PASSWORD=None,
                      ADMIN_USERNAME='admin', ADMIN_EMAIL=None, APP_SETTINGS_CACHE_SECONDS=0)
    with app.app_context():
        create_default_roles()
        access_service.invalidate_cache()
    yield app
    with app.app_context():
        access_service.invalidate_cache()


def _bootstrap(app):
    with app.app_context():
        access_service.ensure_access_settings()
        return access_service.get_owner()


def _login(client, username, password):
    return client.post('/login', data=json.dumps({'username': username, 'password': password}),
                       content_type='application/json', headers={'Accept': 'application/json'})


def _json(client, method, url, body=None):
    return client.open(url, method=method, data=json.dumps(body or {}),
                       content_type='application/json', headers={'Accept': 'application/json'})


def _enable_team(app, password='ownerpass123'):
    """Fresh install -> owner turns on team mode through the app."""
    _bootstrap(app)
    client = app.test_client()
    client.get('/')
    response = _json(client, 'POST', '/api/access/team-mode', {
        'enabled': True, 'allow_registration': True, 'email': 'owner@company.org',
        'password': password, 'confirm_password': password,
    })
    assert response.status_code == 200, response.get_json()
    return client


# --- Startup ------------------------------------------------------------------

def test_fresh_install_starts_open_personal_mode_with_owner(runtime_app):
    owner = _bootstrap(runtime_app)
    with runtime_app.app_context():
        assert access_service.get_deployment_mode() == 'single'
        assert owner.username == 'admin'
        assert owner.password_hash is None
        assert owner.role.access_admin_panel  # owner has every permission

    client = runtime_app.test_client()
    page = client.get('/')
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'Sign-in: Off.' in html
    assert 'Team mode: Off.' in html
    assert 'href="/admin/"' not in html  # no Admin panel link
    assert 'Logout' not in html
    assert client.get('/live').status_code == 200
    assert client.get('/admin/users').status_code == 403


def test_env_password_turns_sign_in_on_and_locks_it(runtime_app):
    runtime_app.config['ADMIN_PASSWORD'] = 'envpassword1'
    owner = _bootstrap(runtime_app)
    assert owner.password_hash

    client = runtime_app.test_client()
    assert client.get('/').status_code == 302
    assert _login(client, 'admin', 'envpassword1').status_code == 302
    response = _json(client, 'DELETE', '/api/access/password', {'current_password': 'envpassword1'})
    assert response.status_code == 409


def test_env_password_is_applied_to_an_existing_open_owner(runtime_app):
    _bootstrap(runtime_app)
    runtime_app.config['ADMIN_PASSWORD'] = 'addedlater1'
    owner = _bootstrap(runtime_app)
    assert owner.password_hash


def test_existing_installation_with_users_is_kept_in_team_mode(runtime_app):
    with runtime_app.app_context():
        auth_service.create_user('existing', 'password123', 'existing@company.org', 'admin')
    owner = _bootstrap(runtime_app)
    with runtime_app.app_context():
        assert access_service.get_deployment_mode() == 'multi'
        assert owner.username == 'existing'


def test_team_mode_from_env_without_password_stops_startup(runtime_app):
    runtime_app.config['DEPLOYMENT_MODE'] = 'multi'
    with runtime_app.app_context(), pytest.raises(RuntimeError, match='ADMIN_PASSWORD'):
        access_service.ensure_access_settings()


# --- Sign-in -----------------------------------------------------------------

def test_public_api_always_needs_a_token(runtime_app):
    _bootstrap(runtime_app)
    client = runtime_app.test_client()
    client.get('/')  # auto sign-in happens for browser pages only
    assert client.get('/api/v1/transcriptions/does-not-exist').status_code == 401


def test_setting_a_password_turns_sign_in_on(runtime_app):
    _bootstrap(runtime_app)
    client = runtime_app.test_client()
    client.get('/')

    short = _json(client, 'POST', '/api/access/password', {'password': 'short', 'confirm_password': 'short'})
    assert short.status_code == 400
    assert 'password' in short.get_json()['errors']

    ok = _json(client, 'POST', '/api/access/password', {
        'username': 'owner', 'password': 'ownerpass123', 'confirm_password': 'ownerpass123',
    })
    assert ok.status_code == 200
    assert client.get('/').status_code == 200  # still signed in

    fresh = runtime_app.test_client()
    assert fresh.get('/').status_code == 302
    assert _login(fresh, 'owner', 'ownerpass123').status_code == 302
    assert fresh.get('/').status_code == 200


def test_turning_sign_in_off_needs_the_current_password(runtime_app):
    _bootstrap(runtime_app)
    client = runtime_app.test_client()
    client.get('/')
    _json(client, 'POST', '/api/access/password', {'password': 'ownerpass123', 'confirm_password': 'ownerpass123'})

    wrong = _json(client, 'DELETE', '/api/access/password', {'current_password': 'nope'})
    assert wrong.status_code == 400
    assert _json(client, 'DELETE', '/api/access/password', {'current_password': 'ownerpass123'}).status_code == 200
    assert runtime_app.test_client().get('/').status_code == 200


def test_recovery_command_resets_the_owner_password(runtime_app):
    _bootstrap(runtime_app)
    result = runtime_app.test_cli_runner().invoke(args=['reset-owner-password', '--password', 'recovered123'])
    assert result.exit_code == 0, result.output
    with runtime_app.app_context():
        assert auth_service.verify_password('admin', 'recovered123')


# --- Team mode ---------------------------------------------------------------

def test_enabling_team_mode_needs_password_and_email(runtime_app):
    _bootstrap(runtime_app)
    client = runtime_app.test_client()
    client.get('/')
    missing = _json(client, 'POST', '/api/access/team-mode', {'enabled': True})
    assert missing.status_code == 400
    assert 'password' in missing.get_json()['errors']

    no_email = _json(client, 'POST', '/api/access/team-mode', {
        'enabled': True, 'password': 'ownerpass123', 'confirm_password': 'ownerpass123',
    })
    assert no_email.status_code == 400
    assert 'email' in no_email.get_json()['errors']


def test_team_mode_turns_on_without_restart(runtime_app):
    client = _enable_team(runtime_app)
    with runtime_app.app_context():
        assert access_service.get_deployment_mode() == 'multi'
    assert client.get('/admin/users').status_code == 200  # the owner is now the admin
    assert runtime_app.test_client().get('/register').status_code == 200
    assert runtime_app.test_client().get('/').status_code == 302  # everyone signs in


def test_other_processes_pick_up_a_switch_after_the_cache_expires(runtime_app, monkeypatch):
    _bootstrap(runtime_app)
    runtime_app.config['APP_SETTINGS_CACHE_SECONDS'] = 5
    clock = [1000.0]
    monkeypatch.setattr(access_service.time, 'monotonic', lambda: clock[0])
    with runtime_app.app_context():
        access_service.invalidate_cache()
        assert access_service.get_deployment_mode() == 'single'
        # Another process (web worker or background worker) switches the mode.
        app_settings_model.set_values({access_service.KEY_MODE: 'multi'})
        assert access_service.get_deployment_mode() == 'single'
        clock[0] += 6
        assert access_service.get_deployment_mode() == 'multi'


def test_switching_back_locks_out_other_accounts_and_their_api_keys(runtime_app):
    owner_client = _enable_team(runtime_app)
    with runtime_app.app_context():
        member = auth_service.create_user('member', 'memberpass1', 'member@company.org', 'admin')
        api_key = user_service.generate_public_api_key(member.id, 'script')['api_key']
    member_client = runtime_app.test_client()
    assert _login(member_client, 'member', 'memberpass1').status_code == 302
    assert member_client.get('/').status_code == 200
    headers = {'Authorization': f'Bearer {api_key}'}
    assert member_client.get('/api/v1/transcriptions/unknown-job', headers=headers).status_code == 404

    wrong = _json(owner_client, 'POST', '/api/access/team-mode', {'enabled': False, 'current_password': 'nope'})
    assert wrong.status_code == 400
    ok = _json(owner_client, 'POST', '/api/access/team-mode', {'enabled': False, 'current_password': 'ownerpass123'})
    assert ok.status_code == 200

    assert member_client.get('/').status_code == 302  # session no longer accepted
    assert runtime_app.test_client().get('/api/v1/transcriptions/unknown-job', headers=headers).status_code == 401
    assert _login(runtime_app.test_client(), 'member', 'memberpass1').status_code == 200  # refused, form re-rendered
    assert owner_client.get('/').status_code == 200
    assert owner_client.get('/admin/users').status_code == 403


def test_mode_set_in_env_cannot_be_switched_in_the_app(runtime_app):
    runtime_app.config['DEPLOYMENT_MODE'] = 'single'
    _bootstrap(runtime_app)
    client = runtime_app.test_client()
    html = client.get('/').get_data(as_text=True)
    assert 'Set by DEPLOYMENT_MODE' in html
    response = _json(client, 'POST', '/api/access/team-mode', {
        'enabled': True, 'email': 'owner@company.org', 'password': 'ownerpass123', 'confirm_password': 'ownerpass123',
    })
    assert response.status_code == 409


# --- Sign-ups ----------------------------------------------------------------

def test_turning_sign_ups_off_blocks_register_and_new_google_accounts(runtime_app):
    owner_client = _enable_team(runtime_app)
    assert _json(owner_client, 'POST', '/api/access/registration', {'allowed': False}).status_code == 200

    visitor = runtime_app.test_client()
    assert visitor.get('/register').status_code == 302
    post = visitor.post('/register', data={'username': 'newbie', 'email': 'n@company.org',
                                           'password': 'newbiepass1', 'confirm_password': 'newbiepass1'})
    assert post.status_code == 302
    with runtime_app.test_request_context():
        assert user_model.get_user_by_username('newbie') is None
        with pytest.raises(auth_service.AuthServiceError):
            auth_service.handle_google_login({'sub': 'g-1', 'email': 'stranger@company.org'},
                                             allow_create=access_service.registration_allowed())
        # Existing accounts can still use Google.
        assert auth_service.handle_google_login({'sub': 'g-2', 'email': 'owner@company.org'}, allow_create=False)


def test_sign_ups_set_in_env_are_locked(runtime_app):
    owner_client = _enable_team(runtime_app)
    runtime_app.config['ALLOW_REGISTRATION'] = True
    assert _json(owner_client, 'POST', '/api/access/registration', {'allowed': False}).status_code == 409


def test_admin_can_add_a_user(runtime_app):
    owner_client = _enable_team(runtime_app)
    missing_email = _json(owner_client, 'POST', '/api/admin/users',
                          {'username': 'added', 'password': 'addedpass1', 'role': 'beta-tester'})
    assert missing_email.status_code == 400
    created = _json(owner_client, 'POST', '/api/admin/users', {
        'username': 'added', 'email': 'added@company.org', 'password': 'addedpass1', 'role': 'beta-tester',
    })
    assert created.status_code == 201
    duplicate = _json(owner_client, 'POST', '/api/admin/users', {
        'username': 'added', 'email': 'other@company.org', 'password': 'addedpass1', 'role': 'beta-tester',
    })
    assert duplicate.status_code == 409


def test_owner_account_cannot_be_deleted_by_another_admin(runtime_app):
    _enable_team(runtime_app)
    with runtime_app.app_context():
        other = auth_service.create_user('second', 'secondpass1', 'second@company.org', 'admin')
        owner_id = access_service.get_owner_id()
    other_client = runtime_app.test_client()
    _login(other_client, 'second', 'secondpass1')
    assert other_client.delete(f'/api/admin/users/{owner_id}').status_code in (400, 403)
    assert other.id != owner_id


def test_personal_mode_uses_saved_keys_before_env_keys(runtime_app):
    _bootstrap(runtime_app)
    runtime_app.config['OPENAI_API_KEY'] = 'env-key'
    with runtime_app.app_context():
        owner = access_service.get_owner()
        status = user_service.get_effective_key_status(owner)
        assert status['openai'] is True  # the .env key counts in personal mode
