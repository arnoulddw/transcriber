# tests/functional/admin/test_admin_panel.py

import pytest
from flask import url_for
from app.models.user import User
from app.models.role import Role

# --- Fixtures ---

@pytest.fixture(scope='function')
def admin_client(app, clean_db):
    """A test client that is logged in as an admin with a clean database."""
    with app.test_client() as client:
        with app.app_context():
            from app.services import auth_service
            from app.models import role as role_model

            # Create an admin role with all permissions
            admin_permissions = {
                'access_admin_panel': True,
                'manage_workflow_templates': True,
            }
            role_model.create_role(
                name='admin_test_role',
                description='Admin role for testing',
                permissions=admin_permissions
            )

            # Create an admin user
            auth_service.create_user(
                username='adminuser',
                password='adminpassword',
                email='admin@example.com',
                role_name='admin_test_role'
            )

            # Log in the admin user
            client.post(url_for('auth.login'), json={
                'username': 'adminuser',
                'password': 'adminpassword'
            })

            yield client

# --- Basic Access Tests ---

def test_admin_panel_unauthorized_access(logged_in_client):
    """
    GIVEN a logged-in non-admin user
    WHEN the user tries to access the admin dashboard
    THEN check that they are redirected or receive a 403 Forbidden error.
    """
    response = logged_in_client.get(url_for('admin_panel.dashboard'))
    assert response.status_code == 403

def test_admin_panel_authorized_access(admin_client):
    """
    GIVEN a logged-in admin user
    WHEN the user accesses the admin dashboard
    THEN check that the page loads successfully.
    """
    response = admin_client.get(url_for('admin_panel.dashboard'))
    assert response.status_code == 200
    assert b"Dashboard overview" in response.data

# --- User Management Tests ---

def test_view_user_list_paginated(admin_client, app):
    """
    GIVEN an admin client and a database with multiple users
    WHEN the admin views the user management page
    THEN check that a paginated list of users is displayed.
    """
    with app.app_context():
        # Create some test users
        from app.services import auth_service
        for i in range(15):
            auth_service.create_user(
                username=f'testuser{i}',
                password=f'password{i}',
                email=f'test{i}@example.com',
                role_name='admin_test_role'
            )
    
    response = admin_client.get(url_for('admin_panel.manage_users'))
    assert response.status_code == 200
    assert b"User management" in response.data
    # Check for a user that should be on the first page
    assert b"testuser1" in response.data

def test_view_user_details(admin_client, app):
    """
    GIVEN an admin client and a specific user in the database
    WHEN the admin views the details of that user
    THEN check that the user's details are displayed correctly.
    """
    with app.app_context():
        from app.services import auth_service
        user = auth_service.create_user(
            username='detaileduser',
            password='password',
            email='detailed@example.com',
            role_name='admin_test_role'
        )
    
    response = admin_client.get(url_for('admin_panel.user_details', user_id=user.id))
    assert response.status_code == 200
    assert b"detaileduser" in response.data
    assert b"detailed@example.com" in response.data

def test_update_user_role(admin_client, app):
    """
    GIVEN an admin client and a user with a specific role
    WHEN the admin updates the user's role
    THEN check that the user's role is updated in the database.
    """
    with app.app_context():
        from app.models import role as role_model
        from app.services import auth_service
        # Create a new role
        new_role = role_model.create_role(name='new_test_role', description='A new role for testing')
        # Create a user to modify
        user_to_modify = auth_service.create_user(
            username='roleupdateuser',
            password='password',
            email='roleupdate@example.com',
            role_name='admin_test_role'
        )

    response = admin_client.put(
        url_for('admin.update_user_role', user_id=user_to_modify.id),
        json={'role_id': new_role.id}
    )
    assert response.status_code == 200

    with app.app_context():
        from app.models import user as user_model
        updated_user = user_model.get_user_by_id(user_to_modify.id)
        assert updated_user.role_id == new_role.id

def test_admin_cannot_change_own_role(admin_client, app):
    """
    GIVEN a logged-in admin user
    WHEN the admin attempts to change their own role
    THEN check that the operation is forbidden.
    """
    with app.app_context():
        from app.models import user as user_model
        from app.models import role as role_model
        admin_user = user_model.get_user_by_username('adminuser')
        # Create another role to switch to
        other_role = role_model.create_role(name='other_role', description='Another role')

    response = admin_client.put(
        url_for('admin.update_user_role', user_id=admin_user.id),
        json={'role_id': other_role.id}
    )
    assert response.status_code == 403
    assert b"Administrators cannot change their own role" in response.data

# --- Role Management Tests ---

def test_view_role_list(admin_client, app):
    """
    GIVEN an admin client and a database with multiple roles
    WHEN the admin views the role management page
    THEN check that a list of roles is displayed.
    """
    with app.app_context():
        from app.models import role as role_model
        role_model.create_role(name='role1', description='Role 1')
        role_model.create_role(name='role2', description='Role 2')

    response = admin_client.get(url_for('admin_panel.manage_roles'))
    assert response.status_code == 200
    assert b"Role management" in response.data
    assert b"role1" in response.data
    assert b"role2" in response.data

def test_create_role(admin_client, app):
    """
    GIVEN an admin client
    WHEN the admin creates a new role with specific permissions
    THEN check that the role is created in the database with the correct permissions.
    """
    role_data = {
        'name': 'new_creative_role',
        'description': 'A new role for creative tasks',
        # Unchecked checkboxes are not sent in form data, so we only include the True value
        'allow_workflows': 'y',
        'use_api_openai_live_transcribe': 'y',
    }
    response = admin_client.post(url_for('admin_panel.create_role'), data=role_data, follow_redirects=True)
    assert response.status_code == 200
    assert b"Role 'new_creative_role' created successfully." in response.data

    with app.app_context():
        from app.models import role as role_model
        new_role = role_model.get_role_by_name('new_creative_role')
        assert new_role is not None
        assert new_role.description == 'A new role for creative tasks'
        # Booleans are submitted as 'y' or not present, so we can't easily check for False
        # Instead, we check that the value is not True
        assert new_role.access_admin_panel is not True
        assert new_role.allow_workflows is True
        assert new_role.use_api_openai_live_transcribe is True

def test_edit_role(admin_client, app):
    """
    GIVEN an admin client and an existing role
    WHEN the admin edits the role's details
    THEN check that the role is updated in the database.
    """
    # Create the role via the app route to ensure same DB/session
    create_resp = admin_client.post(
        url_for('admin_panel.create_role'),
        data={
            'name': 'editable_role',
            'description': 'Initial description'
        },
        follow_redirects=True
    )
    assert create_resp.status_code == 200

    # Retrieve the created role id
    with app.app_context():
        from app.models import role as role_model
        role_to_edit = role_model.get_role_by_name('editable_role')
        assert role_to_edit is not None

    edited_data = {
        'name': 'edited_role_name',
        'description': 'Updated description',
        'access_admin_panel': 'y',
        'use_api_openai_live_transcribe': 'y',
    }
    response = admin_client.post(url_for('admin_panel.edit_role', role_id=role_to_edit.id), data=edited_data, follow_redirects=True)
    assert response.status_code == 200
    assert b"Role 'edited_role_name' updated successfully." in response.data

    with app.app_context():
        from app.models import role as role_model
        # Retrieve by name to avoid any cross-request ID visibility issues
        edited_role = role_model.get_role_by_name('edited_role_name')
        assert edited_role is not None
        assert edited_role.name == 'edited_role_name'
        assert edited_role.description == 'Updated description'
        assert edited_role.access_admin_panel is True
        assert edited_role.use_api_openai_live_transcribe is True

def test_delete_role(admin_client, app):
    """
    GIVEN an admin client and a role that is not in use
    WHEN the admin deletes the role
    THEN check that the role is removed from the database.
    """
    with app.app_context():
        from app.models import role as role_model
        role_to_delete = role_model.create_role(name='deletable_role', description='A role to be deleted')

    response = admin_client.post(url_for('admin_panel.delete_role', role_id=role_to_delete.id), follow_redirects=True)
    assert response.status_code == 200
    assert f"Role (ID: {role_to_delete.id}) deleted successfully.".encode() in response.data

    with app.app_context():
        from app.models import role as role_model
        deleted_role = role_model.get_role_by_id(role_to_delete.id)
        assert deleted_role is None

def test_cannot_delete_role_in_use(admin_client, app):
    """
    GIVEN an admin client and a role that is assigned to a user
    WHEN the admin attempts to delete the role
    THEN check that the deletion fails and an appropriate message is shown.
    """
    with app.app_context():
        from app.models import role as role_model
        from app.services import auth_service
        role_in_use = role_model.create_role(name='role_in_use', description='A role assigned to a user')
        auth_service.create_user(
            username='userwithrole',
            password='password',
            email='userwithrole@example.com',
            role_name='role_in_use'
        )

    response = admin_client.post(url_for('admin_panel.delete_role', role_id=role_in_use.id), follow_redirects=True)
    assert response.status_code == 200
    assert b"Error deleting role: Cannot delete role 'role_in_use' as 1 user(s) are assigned to it. Reassign users first." in response.data

    with app.app_context():
        from app.models import role as role_model
        undel_role = role_model.get_role_by_id(role_in_use.id)
        assert undel_role is not None
