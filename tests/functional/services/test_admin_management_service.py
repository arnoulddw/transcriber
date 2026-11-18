# tests/functional/services/test_admin_management_service.py

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from app.services import admin_management_service
from app.services.exceptions import AdminServiceError
from app.models.user import User
from app.models.role import Role
from app.models.template_prompt import TemplatePrompt

# --- Fixtures ---

@pytest.fixture
def mock_db_models(app):
    """Mocks all database models used by the admin management service."""
    with app.test_request_context():
        with patch('app.services.admin_management_service.user_model', autospec=True) as mock_user, \
             patch('app.services.admin_management_service.role_model', autospec=True) as mock_role, \
             patch('app.services.admin_management_service.template_prompt_model', autospec=True) as mock_template, \
             patch('app.services.admin_management_service.user_prompt_model', autospec=True) as mock_user_prompt, \
             patch('app.services.admin_management_service.transcription_utils', autospec=True) as mock_transcription, \
             patch('app.services.admin_management_service.user_utils', autospec=True) as mock_user_utils, \
             patch('app.services.admin_management_service.auth_service', autospec=True) as mock_auth, \
             patch('app.services.admin_management_service.user_service', autospec=True) as mock_user_service, \
             patch('app.services.admin_management_service.admin_metrics_service', autospec=True) as mock_metrics:

            # Setup mock return values
            from unittest.mock import PropertyMock

            user_instance = User(id=1, username='testuser', email='test@test.com', password_hash='dummy_hash', role_id=1, created_at=datetime.now(timezone.utc))
            
            # Mock the 'role' property (restored below so it can't leak into later tests)
            original_role_property = User.__dict__['role']
            type(user_instance).role = PropertyMock(return_value=Role(id=1, name='admin'))
            
            mock_user.get_user_by_id.return_value = user_instance
            mock_role.get_role_by_id.return_value = Role(id=1, name='admin')
            mock_role.get_role_by_name.return_value = Role(id=1, name='admin')
            mock_auth.create_user.return_value = User(id=2, username='newuser', email='new@test.com', password_hash='dummy_hash', role_id=1, created_at=datetime.now(timezone.utc))
            
            yield {
                "user": mock_user, "role": mock_role, "template": mock_template,
                "user_prompt": mock_user_prompt, "transcription": mock_transcription,
                "user_utils": mock_user_utils, "auth": mock_auth, "user_service": mock_user_service,
                "metrics": mock_metrics
            }
            User.role = original_role_property

# --- User Management Tests ---

def test_list_paginated_users_success(app, mock_db_models):
    """Tests successful retrieval of paginated users."""
    mock_db_models['user_utils'].count_all_users.return_value = 1
    mock_db_models['user_utils'].get_paginated_users_with_details.return_value = [User(id=1, username='test', email='test@test.com', password_hash='dummy', role_id=1, created_at=datetime.now(timezone.utc))]
    
    with app.app_context():
        users, meta = admin_management_service.list_paginated_users(page=1, per_page=10)
        assert len(users) == 1
        assert meta['total_users'] == 1

def test_get_user_details_with_stats_success(app, mock_db_models):
    """Tests successful retrieval of user details and stats."""
    with app.app_context():
        details = admin_management_service.get_user_details_with_stats(1)
        assert details is not None
        assert details['username'] == 'testuser'
        assert 'stats' in details

def test_admin_create_user_success(app, mock_db_models):
    """Tests successful user creation by an admin."""
    with app.app_context():
        user = admin_management_service.admin_create_user('newuser', 'password', 'new@test.com', 'admin')
        assert user.username == 'newuser'

def test_admin_create_user_duplicate_username(app, mock_db_models):
    """Tests that creating a user with a duplicate username fails."""
    mock_db_models['auth'].create_user.return_value = None
    mock_db_models['user'].get_user_by_username.return_value = User(id=1, username='newuser', email='new@test.com', password_hash='dummy', role_id=1, created_at=datetime.now(timezone.utc))
    with app.app_context():
        with pytest.raises(AdminServiceError, match="Username 'newuser' is already taken."):
            admin_management_service.admin_create_user('newuser', 'password', 'new@test.com', 'admin')

def test_admin_delete_user_success(app, mock_db_models):
    """Tests successful user deletion by an admin."""
    mock_db_models['user'].delete_user_by_id.return_value = True
    with app.app_context():
        result = admin_management_service.admin_delete_user(user_id_to_delete=2, current_admin_id=1)
        assert result is True

def test_admin_delete_user_self_delete_fails(app, mock_db_models):
    """Tests that an admin cannot delete themselves."""
    with app.app_context():
        with pytest.raises(AdminServiceError, match="Administrators cannot delete their own account."):
            admin_management_service.admin_delete_user(user_id_to_delete=1, current_admin_id=1)

def test_admin_reset_user_password_success(app, mock_db_models):
    """Tests successful password reset by an admin."""
    mock_db_models['user'].update_user_password_hash.return_value = True
    with app.app_context():
        result = admin_management_service.admin_reset_user_password(2, 'newpassword123', 1)
        assert result is True

def test_update_user_role_admin_success(app, mock_db_models):
    """Tests successful role update by an admin."""
    mock_db_models['user'].update_user_role.return_value = True
    with app.app_context():
        admin_management_service.update_user_role_admin(2, 2, 1)
        mock_db_models['user'].update_user_role.assert_called_once_with(2, 2)

# --- Role Management Tests ---

def test_get_all_roles_success(app, mock_db_models):
    """Tests successful retrieval of all roles."""
    mock_db_models['role'].get_all_roles.return_value = [Role(id=1, name='admin')]
    with app.app_context():
        roles = admin_management_service.get_all_roles()
        assert len(roles) == 1
        assert roles[0]['name'] == 'admin'

def test_create_role_success(app, mock_db_models):
    """Tests successful role creation."""
    mock_db_models['role'].get_role_by_name.return_value = None
    mock_db_models['role'].create_role.return_value = Role(id=2, name='new-role')
    with app.app_context():
        role = admin_management_service.create_role({'name': 'new-role', 'description': 'A new role'})
        assert role.name == 'new-role'

def test_create_role_duplicate_name_fails(app, mock_db_models):
    """Tests that creating a role with a duplicate name fails."""
    mock_db_models['role'].get_role_by_name.return_value = Role(id=1, name='admin')
    with app.app_context():
        with pytest.raises(AdminServiceError, match="Role name 'admin' already exists."):
            admin_management_service.create_role({'name': 'admin'})

def test_update_role_success(app, mock_db_models):
    """Tests successful role update."""
    mock_db_models['role'].update_role.return_value = True
    mock_db_models['role'].get_role_by_id.return_value = Role(id=1, name='old-name')
    mock_db_models['role'].get_role_by_name.return_value = None
    with app.app_context():
        result = admin_management_service.update_role(1, {'name': 'new-name'})
        assert result is True

def test_delete_role_success(app, mock_db_models):
    """Tests successful role deletion."""
    mock_db_models['role'].delete_role.return_value = (True, "Success")
    with app.app_context():
        admin_management_service.delete_role(1)
        mock_db_models['role'].delete_role.assert_called_once_with(1)

# --- Template Prompt Management Tests ---

def test_get_template_prompts_success(app, mock_db_models):
    """Tests successful retrieval of template prompts."""
    mock_db_models['template'].get_templates.return_value = [TemplatePrompt(id=1, title='Test Prompt')]
    with app.app_context():
        prompts = admin_management_service.get_template_prompts()
        assert len(prompts) == 1
        assert prompts[0].title == 'Test Prompt'
        assert prompts[0].unique_user_count == 0
        assert prompts[0].total_usage_count == 0


def test_get_template_prompts_with_usage_stats(app, mock_db_models):
    """Ensures usage counts are attached when requested."""
    template = TemplatePrompt(id=1, title='Popular Prompt')
    mock_db_models['template'].get_templates.return_value = [template]
    mock_db_models['template'].get_template_usage_stats.return_value = {
        1: {'unique_users': 4, 'total_uses': 12}
    }
    with app.app_context():
        prompts = admin_management_service.get_template_prompts(include_usage=True)
        assert prompts[0].unique_user_count == 4
        assert prompts[0].total_usage_count == 12

def test_add_template_prompt_success(app, mock_db_models):
    """Tests successful creation of a template prompt."""
    mock_db_models['template'].add_template.return_value = TemplatePrompt(id=2, title='New Prompt')
    with app.app_context():
        prompt = admin_management_service.add_template_prompt('New Prompt', 'Text')
        assert prompt.title == 'New Prompt'
        mock_db_models['user_service'].sync_templates_for_all_users.assert_called_once()

def test_update_template_prompt_success(app, mock_db_models):
    """Tests successful update of a template prompt."""
    mock_db_models['template'].update_template.return_value = True
    with app.app_context():
        result = admin_management_service.update_template_prompt(1, 'Updated Title', 'Updated Text')
        assert result is True
        mock_db_models['user_service'].sync_templates_for_all_users.assert_called_once()

def test_delete_template_prompt_success(app, mock_db_models):
    """Tests successful deletion of a template prompt."""
    mock_db_models['user_prompt'].delete_prompts_by_source_id.return_value = 1
    mock_db_models['template'].delete_template.return_value = True
    with app.app_context():
        result = admin_management_service.delete_template_prompt(1)
        assert result is True
        mock_db_models['user_prompt'].delete_prompts_by_source_id.assert_called_once_with(1)
        mock_db_models['template'].delete_template.assert_called_once_with(1)
