# tests/functional/api/test_auth_google.py
# Functional tests for the Google Sign-In callback endpoint.

from types import SimpleNamespace
from unittest.mock import MagicMock


def _setup_google_mocks(monkeypatch):
    """Helper to mock Google auth service interactions and capture calls."""
    captured = {}

    def fake_verify(token):
        captured['token'] = token
        return {'sub': 'google-user-123', 'email': 'user@example.com'}

    dummy_user = SimpleNamespace(id=42, email='user@example.com')

    def fake_handle(idinfo, allow_create=True):
        captured['idinfo'] = idinfo
        captured['allow_create'] = allow_create
        return dummy_user

    login_spy = MagicMock(name="login_user_spy")

    monkeypatch.setattr('app.api.auth.auth_service.verify_google_id_token', fake_verify)
    monkeypatch.setattr('app.api.auth.auth_service.handle_google_login', fake_handle)
    monkeypatch.setattr('app.api.auth.login_user', login_spy)

    captured['user'] = dummy_user
    captured['login_spy'] = login_spy
    return captured


def test_google_callback_redirects_on_success(client, app, monkeypatch):
    """HTML form submissions should redirect to '/' after successful Google login."""
    with app.app_context():
        app.config['GOOGLE_CLIENT_ID'] = 'test-client-id'

    captured = _setup_google_mocks(monkeypatch)

    response = client.post(
        '/api/auth/google-callback',
        data={'credential': 'test-token'},
        headers={'Accept': 'text/html'}
    )

    assert response.status_code == 302
    assert response.headers['Location'] == '/'
    assert captured['token'] == 'test-token'
    captured['login_spy'].assert_called_once_with(captured['user'], remember=True)


def test_google_callback_returns_json_when_requested(client, app, monkeypatch):
    """JSON clients (e.g., fetch) should receive a JSON success payload."""
    with app.app_context():
        app.config['GOOGLE_CLIENT_ID'] = 'test-client-id'

    captured = _setup_google_mocks(monkeypatch)

    response = client.post(
        '/api/auth/google-callback?next=%2Fdashboard',
        json={'id_token': 'token-123'},
        headers={'Accept': 'application/json'}
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload == {'success': True, 'message': 'Login successful.', 'redirect': '/dashboard'}
    assert captured['token'] == 'token-123'
    captured['login_spy'].assert_called_once_with(captured['user'], remember=True)
