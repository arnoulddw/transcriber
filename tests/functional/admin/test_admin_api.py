import pytest
from unittest.mock import MagicMock, patch

from app.services.admin_management_service import AdminServiceError
from app.services.pricing_service import PricingServiceError


@pytest.fixture(autouse=True)
def ensure_context(app):
    with app.app_context():
        yield


def test_list_users_api(admin_client):
    sample_users = [{"id": 1, "username": "admin"}, {"id": 2, "username": "member"}]
    with patch(
        "app.api.admin.admin_management_service.list_paginated_users",
        return_value=(sample_users, {"total_users": 2}),
    ) as mock_list:
        response = admin_client.get("/api/admin/users")

    assert response.status_code == 200
    assert response.get_json() == sample_users
    mock_list.assert_called_once_with(page=1, per_page=10000)


def test_get_user_details_api(admin_client):
    details = {"id": 2, "username": "member", "stats": {"minutes": 10}}
    with patch(
        "app.api.admin.admin_management_service.get_user_details_with_stats",
        return_value=details,
    ) as mock_get:
        response = admin_client.get("/api/admin/users/2")

    assert response.status_code == 200
    assert response.get_json()["username"] == "member"
    mock_get.assert_called_once_with(2)


def test_create_user_api(admin_client):
    new_user = MagicMock(id=3, username="newuser")
    with patch(
        "app.api.admin.admin_management_service.admin_create_user",
        return_value=new_user,
    ) as mock_create:
        response = admin_client.post(
            "/api/admin/users",
            json={
                "username": "newuser",
                "password": "password123",
                "email": "new@example.com",
                "role": "beta-tester",
            },
        )

    assert response.status_code == 201
    data = response.get_json()
    assert data["message"] == "User created successfully."
    assert data["user"]["username"] == "newuser"
    mock_create.assert_called_once()


def test_create_user_duplicate_username(admin_client):
    with patch(
        "app.api.admin.admin_management_service.admin_create_user",
        side_effect=AdminServiceError("Username already taken"),
    ):
        response = admin_client.post(
            "/api/admin/users",
            json={"username": "existing", "password": "password123", "email": "existing@company.org"},
        )

    assert response.status_code == 409
    assert "already taken" in response.get_json()["error"]


def test_delete_user_api(admin_client):
    with patch(
        "app.api.admin.admin_management_service.admin_delete_user"
    ) as mock_delete:
        response = admin_client.delete("/api/admin/users/5")

    assert response.status_code == 200
    assert response.get_json()["message"] == "User deleted successfully."
    mock_delete.assert_called_once_with(5, 1)


def test_delete_user_not_found(admin_client):
    with patch(
        "app.api.admin.admin_management_service.admin_delete_user",
        side_effect=AdminServiceError("User not found"),
    ):
        response = admin_client.delete("/api/admin/users/9")

    assert response.status_code == 404
    assert "not found" in response.get_json()["error"].lower()


def test_reset_password_api(admin_client):
    with patch(
        "app.api.admin.admin_management_service.admin_reset_user_password"
    ) as mock_reset:
        response = admin_client.post(
            "/api/admin/users/4/reset-password",
            json={"new_password": "newpassword123"},
        )

    assert response.status_code == 200
    assert response.get_json()["message"] == "Password reset successfully."
    mock_reset.assert_called_once_with(4, "newpassword123", 1)


def test_update_user_role_api(admin_client):
    with patch(
        "app.api.admin.admin_management_service.update_user_role_admin"
    ) as mock_update:
        response = admin_client.put(
            "/api/admin/users/4/role", json={"role_id": 7}
        )

    assert response.status_code == 200
    assert response.get_json()["message"] == "User role updated successfully."
    mock_update.assert_called_once_with(4, 7, 1)


def test_create_template_workflow_api(admin_client):
    new_template = MagicMock(
        id=10, title="Template", prompt_text="Do this", language="en", color="#ffffff"
    )
    with patch(
        "app.api.admin.admin_management_service.add_template_prompt",
        return_value=new_template,
    ) as mock_add:
        response = admin_client.post(
            "/api/admin/template-workflows",
            json={
                "title": "Template",
                "prompt_text": "Do this",
                "language": "en",
                "color": "#ffffff",
            },
        )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["template"]["title"] == "Template"
    mock_add.assert_called_once()


def test_update_template_workflow_api(admin_client):
    with patch(
        "app.api.admin.admin_management_service.update_template_prompt",
        return_value=True,
    ) as mock_update:
        response = admin_client.put(
            "/api/admin/template-workflows/10",
            json={
                "title": "Updated",
                "prompt_text": "Updated prompt",
                "language": "en",
                "color": "#000000",
            },
        )

    assert response.status_code == 200
    assert response.get_json()["message"] == "Template workflow updated successfully."
    mock_update.assert_called_once_with(
        prompt_id=10,
        title="Updated",
        prompt_text="Updated prompt",
        language="en",
        color="#000000",
    )


def test_pricing_get(admin_client):
    with patch(
        "app.api.admin.pricing_service.get_all_prices",
        return_value={"transcription": {"whisper": 0.01}},
    ) as mock_get:
        response = admin_client.get("/api/admin/pricing")

    assert response.status_code == 200
    assert response.get_json()["transcription"]["whisper"] == 0.01
    mock_get.assert_called_once()


def test_pricing_update(admin_client):
    with patch(
        "app.api.admin.pricing_service.update_prices"
    ) as mock_update:
        response = admin_client.post(
            "/api/admin/pricing",
            json={"workflow": {"GEMINI": 0.002}},
        )

    assert response.status_code == 200
    assert response.get_json()["success"] is True
    mock_update.assert_called_once_with({"workflow": {"GEMINI": 0.002}})


def test_pricing_update_error(admin_client):
    with patch(
        "app.api.admin.pricing_service.update_prices",
        side_effect=PricingServiceError("DB error"),
    ):
        response = admin_client.post(
            "/api/admin/pricing",
            json={"workflow": {"GEMINI": 0.002}},
        )

    assert response.status_code == 500
    assert "DB error" in response.get_json()["error"]
