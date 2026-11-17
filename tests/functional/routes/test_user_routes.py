# tests/functional/routes/test_user_routes.py
# Contains functional tests for user-related routes, such as profile and settings.

import pytest
from flask import url_for
from werkzeug.datastructures import MultiDict
from app.models.user import User

# --- Test User Profile Endpoints ---

def test_get_profile(logged_in_client):
    """
    GIVEN a logged-in user
    WHEN the '/api/user/profile' endpoint is requested (GET)
    THEN check that the response is valid and contains the user's profile data.
    """
    response = logged_in_client.get(url_for('user_settings.get_profile'))
    assert response.status_code == 200
    json_data = response.get_json()
    assert 'username' in json_data
    assert 'email' in json_data
    assert json_data['username'] == 'testuser'

def test_update_profile_success(logged_in_client_with_permissions):
    """
    GIVEN a logged-in user
    WHEN the '/api/user/profile' endpoint is requested (PUT) with valid data
    THEN check that the response is successful and the user's profile is updated.
    """
    new_profile_data = {
        'username': 'testuser_permissions',
        'email': 'test_permissions@example.com',
        'first_name': 'Test',
        'last_name': 'UserUpdated',
        'default_content_language': 'es',
        'default_transcription_model': 'gpt-4o-transcribe',
        'enable_auto_title_generation': True,
        'language': 'en'
    }
    response = logged_in_client_with_permissions.put(url_for('user_settings.update_profile'), json=new_profile_data)
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data['message'] == 'Profile updated successfully.'

    # Verify the changes in the database
    from app.models.user import get_user_by_username
    user = get_user_by_username('testuser_permissions')
    assert user.first_name == 'Test'
    assert user.last_name == 'UserUpdated'
    assert user.default_content_language == 'es'
    assert user.default_transcription_model == 'openai:gpt-4o-transcribe'
    assert user.enable_auto_title_generation is True

def test_update_profile_invalid_data(logged_in_client):
    """
    GIVEN a logged-in user
    WHEN the '/api/user/profile' endpoint is requested (PUT) with invalid data
    THEN check that the response indicates a validation error.
    """
    new_profile_data = {
        'email': 'not-an-email',
    }
    response = logged_in_client.put(url_for('user_settings.update_profile'), json=new_profile_data)
    assert response.status_code == 400
    json_data = response.get_json()
    assert 'error' in json_data
    assert 'errors' in json_data
    assert 'email' in json_data['errors']

def test_change_password_success(logged_in_client_with_permissions):
    """
    GIVEN a logged-in user
    WHEN the '/api/user/change-password' endpoint is requested (POST) with valid data
    THEN check that the response is successful.
    """
    password_data = {
        'current_password': 'password123',
        'new_password': 'newpassword123',
        'confirm_new_password': 'newpassword123'
    }
    response = logged_in_client_with_permissions.post(url_for('user_settings.change_password'), json=password_data)
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data['message'] == 'Password changed successfully.'

def test_change_password_invalid_current_password(logged_in_client_with_permissions):
    """
    GIVEN a logged-in user
    WHEN the '/api/user/change-password' endpoint is requested (POST) with an invalid current password
    THEN check that the response indicates an error.
    """
    password_data = {
        'current_password': 'wrongpassword',
        'new_password': 'newpassword123',
        'confirm_new_password': 'newpassword123'
    }
    response = logged_in_client_with_permissions.post(url_for('user_settings.change_password'), json=password_data)
    assert response.status_code == 400
    json_data = response.get_json()
    assert 'error' in json_data
    assert json_data['field'] == 'current_password'

# --- Test API Key Management Endpoints ---

def test_get_api_key_status_requires_management_permission(logged_in_client):
    """
    GIVEN a logged-in user
    WHEN the '/api/user/keys' endpoint is requested (GET)
    THEN check that the response is valid and contains the API key status.
    """
    response = logged_in_client.get(url_for('user_settings.get_api_key_status'))
    assert response.status_code == 403


def test_get_api_key_status(logged_in_client_with_permissions):
    response = logged_in_client_with_permissions.get(url_for('user_settings.get_api_key_status'))
    assert response.status_code == 200
    json_data = response.get_json()
    assert {'openai', 'assemblyai', 'gemini', 'openrouter'} <= set(json_data)
    assert json_data['openai'] is False


def test_api_key_mutations_require_management_permission(logged_in_client):
    key_data = {'service': 'openai', 'api_key': 'sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'}
    save_response = logged_in_client.post(url_for('user_settings.save_api_key'), json=key_data)
    delete_response = logged_in_client.delete(url_for('user_settings.delete_api_key', service='openai'))
    assert save_response.status_code == 403
    assert delete_response.status_code == 403

def test_save_and_delete_api_key(logged_in_client_with_permissions):
    """
    GIVEN a logged-in user
    WHEN an API key is saved and then deleted
    THEN check that the operations are successful.
    """
    # Save API key
    key_data = {'service': 'openai', 'api_key': 'sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'}
    response = logged_in_client_with_permissions.post(url_for('user_settings.save_api_key'), json=key_data)
    assert response.status_code == 200

    # Check status
    response = logged_in_client_with_permissions.get(url_for('user_settings.get_api_key_status'))
    assert response.status_code == 200
    assert response.get_json()['openai'] is True

    # Delete API key
    response = logged_in_client_with_permissions.delete(url_for('user_settings.delete_api_key', service='openai'))
    assert response.status_code == 200

    # Check status again
    response = logged_in_client_with_permissions.get(url_for('user_settings.get_api_key_status'))
    assert response.status_code == 200
    assert response.get_json()['openai'] is False


def test_save_api_key_with_several_purposes(logged_in_client_with_permissions):
    form_data = MultiDict([
        ('service', 'openai'),
        ('api_key', 'sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'),
        ('model_name', 'gpt-transcribe'),
        ('model_purpose', 'transcription'),
        ('model_purpose', 'live'),
    ])
    response = logged_in_client_with_permissions.post(
        url_for('user_settings.save_api_key'), data=form_data
    )
    assert response.status_code == 200

    status = logged_in_client_with_permissions.get(
        url_for('user_settings.get_api_key_status')
    ).get_json()
    [entry] = status['provider_keys']['openai']
    assert set(entry['model_purposes']) == {'transcription', 'live'}


def test_save_and_delete_openrouter_api_key(logged_in_client_with_permissions):
    key_data = {
        'service': 'openrouter',
        'api_key': 'sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
        'openrouter_model': 'openai/gpt-transcribe',
        'openrouter_model_purpose': 'transcription',
    }
    response = logged_in_client_with_permissions.post(
        url_for('user_settings.save_api_key'), json=key_data
    )
    assert response.status_code == 200

    status = logged_in_client_with_permissions.get(
        url_for('user_settings.get_api_key_status')
    ).get_json()
    assert status['openrouter'] is True

    response = logged_in_client_with_permissions.delete(
        url_for('user_settings.delete_api_key', service='openrouter')
    )
    assert response.status_code == 200
    status = logged_in_client_with_permissions.get(
        url_for('user_settings.get_api_key_status')
    ).get_json()
    assert status['openrouter'] is False

# --- Test User Readiness Endpoint ---

def test_get_user_readiness(logged_in_client):
    """
    GIVEN a logged-in user
    WHEN the '/api/user/readiness' endpoint is requested (GET)
    THEN check that the response is valid and contains readiness data.
    """
    response = logged_in_client.get(url_for('user_settings.get_user_readiness'))
    assert response.status_code == 200
    json_data = response.get_json()
    assert 'api_keys' in json_data
    assert 'permissions' in json_data
    assert 'limits' in json_data
    assert 'usage' in json_data

# --- Test Prompt Management Endpoints ---

def test_manage_prompts_page(logged_in_client_with_permissions):
    """
    GIVEN a logged-in user with permissions
    WHEN the '/manage-prompts' page is requested
    THEN check that the page loads successfully.
    """
    response = logged_in_client_with_permissions.get(url_for('main.manage_prompts'))
    assert response.status_code == 200
    assert b"<title>Manage your workflows</title>" in response.data

def test_get_user_prompts(logged_in_client):
    """
    GIVEN a logged-in user
    WHEN the '/api/user/prompts' endpoint is requested (GET)
    THEN check that the response is valid and contains a list of prompts.
    """
    response = logged_in_client.get(url_for('user_settings.get_user_prompts_api'))
    assert response.status_code == 200
    json_data = response.get_json()
    assert isinstance(json_data, list)

def test_create_update_delete_prompt(logged_in_client):
    """
    GIVEN a logged-in user
    WHEN a new prompt is created, updated, and then deleted
    THEN check that all operations are successful.
    """
    # Create a new prompt
    new_prompt_data = {
        'title': 'Test Prompt',
        'prompt_text': 'This is a test prompt.',
        'color': '#ff0000'
    }
    response = logged_in_client.post(url_for('user_settings.save_user_prompt_api'), json=new_prompt_data)
    assert response.status_code == 201
    prompt = response.get_json()['prompt']
    prompt_id = prompt['id']

    # Update the prompt
    updated_prompt_data = {
        'title': 'Updated Test Prompt',
        'prompt_text': 'This is the updated test prompt.',
        'color': '#00ff00'
    }
    response = logged_in_client.put(url_for('user_settings.update_user_prompt_api', prompt_id=prompt_id), json=updated_prompt_data)
    assert response.status_code == 200

    # Delete the prompt
    response = logged_in_client.delete(url_for('user_settings.delete_user_prompt_api', prompt_id=prompt_id))
    assert response.status_code == 200