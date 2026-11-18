# app/api/admin.py
# Defines the Blueprint for administration-related API endpoints.

import logging
from flask import Blueprint, request, jsonify, current_app
from flask_login import current_user # To identify the admin making the request

# Import decorators and services
from app.core.decorators import admin_required, permission_required # Added permission_required
# Import management service
from app.services import admin_management_service, pricing_service
from app.services.admin_management_service import AdminServiceError # Specific exception
from app.services.auth_service import AuthServiceError
from app.services.pricing_service import PricingServiceError
from app.extensions import limiter
from app.models import llm_catalog as llm_catalog_model
from app.models import transcription_catalog as transcription_catalog_model
 
 # Define the Blueprint
# The first argument is the blueprint name, used in url_for() calls (e.g., url_for('admin.list_users'))
# The second argument is the import name, usually __name__
# The third argument (optional) is the URL prefix for all routes in this blueprint
admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')

# --- User Management API Endpoints ---
# ... (existing user endpoints remain unchanged) ...
@admin_bp.route('/users', methods=['GET'])
@admin_required
@limiter.limit("60 per minute")
def list_users():
    """
    API endpoint for admins to list all users.
    Returns a JSON list of user objects (excluding sensitive data).
    DEPRECATED: Paginated list is now rendered server-side. This might be removed or adapted.
    """
    admin_id = current_user.id
    log_prefix = f"[API:Admin:{admin_id}:ListUsers]"
    logging.debug(f"{log_prefix} Request received.")
    try:
        # Call the service layer function to get user data
        # Call management service (Note: list_all_users might be deprecated/removed)
        # For now, let's assume it exists in management service or adapt if needed
        # users = admin_management_service.list_all_users()
        # Let's use the paginated one as an example, though the route doesn't take page args
        users, _ = admin_management_service.list_paginated_users(page=1, per_page=10000) # Get all for API
        logging.debug(f"{log_prefix} Returning {len(users)} users.")
        return jsonify(users), 200
    except Exception as e:
        # Catch unexpected errors in the service layer
        logging.error(f"{log_prefix} Error listing users: {e}", exc_info=True)
        return jsonify({'error': 'Failed to retrieve user list due to an internal error.'}), 500

@admin_bp.route('/users/<int:user_id>', methods=['GET'])
@admin_required
@limiter.limit("60 per minute")
def get_user_details(user_id):
    """
    API endpoint for admins to get details and stats for a specific user.
    Returns a JSON object with user details and usage statistics.
    """
    admin_id = current_user.id
    log_prefix = f"[API:Admin:{admin_id}:UserDetails:{user_id}]"
    logging.debug(f"{log_prefix} Request received.")
    try:
        # Call the service layer function
        # Call management service
        details = admin_management_service.get_user_details_with_stats(user_id)
        if details:
            logging.debug(f"{log_prefix} Returning details for user '{details.get('username')}'.")
            return jsonify(details), 200
        else:
            # User not found by the service
            logging.warning(f"{log_prefix} User not found.")
            return jsonify({'error': 'User not found.'}), 404
    except Exception as e:
        logging.error(f"{log_prefix} Error getting user details: {e}", exc_info=True)
        return jsonify({'error': 'Failed to retrieve user details due to an internal error.'}), 500

@admin_bp.route('/users', methods=['POST'])
@admin_required
@limiter.limit("20 per minute")
def create_user():
    """
    API endpoint for admins to create a new user.
    Expects JSON payload: {"username": "...", "password": "...", "role": "..."}
    Returns the created user's basic info on success (201).
    """
    admin_id = current_user.id
    log_prefix = f"[API:Admin:{admin_id}:CreateUser]"

    # Validate request payload
    data = request.get_json()
    if not data:
        logging.warning(f"{log_prefix} Received empty request body.")
        return jsonify({'error': 'Request body must be JSON.'}), 400
    username = data.get('username')
    password = data.get('password')
    role_name = data.get('role', 'beta-tester') # Default role if not specified

    if not username or not password:
        logging.warning(f"{log_prefix} Missing username or password in request.")
        return jsonify({'error': 'Missing username or password in request body.'}), 400
    if not data.get('email'):
        return jsonify({'error': 'An email address is required.'}), 400
    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters long.'}), 400

    try:
        # Call the service layer function
        # Call management service
        new_user = admin_management_service.admin_create_user(username, password, email=data.get('email'), role_name=role_name) # Pass email too
        # Return basic info of the created user
        return jsonify({
            'message': 'User created successfully.',
            'user': {
                'id': new_user.id,
                'username': new_user.username,
                'role': role_name # Return the requested role name
            }
        }), 201 # HTTP 201 Created
    except (AdminServiceError, AuthServiceError) as ase:
        # Handle specific errors from the service (e.g., duplicate user, invalid role)
        logging.error(f"{log_prefix} Failed to create user '{username}': {ase}")
        # Return 409 Conflict for duplicate username/email, 400 for others
        message = str(ase)
        status_code = 409 if ('already taken' in message or 'already registered' in message) else 400
        return jsonify({'error': message}), status_code
    except Exception as e:
        # Handle unexpected errors
        logging.error(f"{log_prefix} Unexpected error creating user '{username}': {e}", exc_info=True)
        return jsonify({'error': 'Failed to create user due to an internal error.'}), 500

@admin_bp.route('/users/<int:user_id>', methods=['DELETE'])
@admin_required
@limiter.limit("20 per minute")
def delete_user(user_id):
    """
    API endpoint for admins to delete a user account.
    Prevents self-deletion.
    """
    admin_id = current_user.id
    log_prefix = f"[API:Admin:{admin_id}:DeleteUser:{user_id}]"
    logging.warning(f"{log_prefix} Received request to delete user.")

    try:
        # Call the service layer function, passing the admin's ID for self-delete check
        # Call management service
        admin_management_service.admin_delete_user(user_id, admin_id)
        return jsonify({'message': 'User deleted successfully.'}), 200
    except AdminServiceError as ase:
        # Handle specific errors from the service
        logging.error(f"{log_prefix} Failed to delete user: {ase}")
        # Determine appropriate status code based on error type
        if "not found" in str(ase).lower():
            status_code = 404 # Not Found
        elif "cannot delete their own" in str(ase).lower():
            status_code = 403 # Forbidden
        else:
            status_code = 400 # Bad Request (other validation errors)
        return jsonify({'error': str(ase)}), status_code
    except Exception as e:
        # Handle unexpected errors
        logging.error(f"{log_prefix} Unexpected error deleting user: {e}", exc_info=True)
        return jsonify({'error': 'Failed to delete user due to an internal error.'}), 500

@admin_bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@admin_required
@limiter.limit("10 per minute")
def reset_password(user_id):
    """
    API endpoint for admins to reset a user's password.
    Expects JSON payload: {"new_password": "..."}
    """
    admin_id = current_user.id
    log_prefix = f"[API:Admin:{admin_id}:ResetPwd:{user_id}]"

    # Validate request payload
    data = request.get_json()
    if not data or 'new_password' not in data:
        logging.warning(f"{log_prefix} Missing new_password in request body.")
        return jsonify({'error': 'Missing new_password in request body.'}), 400

    new_password = data.get('new_password')

    try:
        # Call the service layer function
        # Call management service
        admin_management_service.admin_reset_user_password(user_id, new_password, admin_id)
        return jsonify({'message': 'Password reset successfully.'}), 200
    except AdminServiceError as ase:
        # Handle specific errors from the service (user not found, password too short)
        logging.error(f"{log_prefix} Failed to reset password: {ase}")
        status_code = 404 if "not found" in str(ase).lower() else 400 # Not Found or Bad Request
        return jsonify({'error': str(ase)}), status_code
    except Exception as e:
        # Handle unexpected errors
        logging.error(f"{log_prefix} Unexpected error resetting password: {e}", exc_info=True)
        return jsonify({'error': 'Failed to reset password due to an internal error.'}), 500

@admin_bp.route('/users/<int:user_id>/role', methods=['PUT'])
@admin_required
@limiter.limit("20 per minute")
def update_user_role(user_id):
    """
    API endpoint for admins to update a user's role inline.
    Expects JSON payload: {"role_id": <new_role_id>}
    """
    admin_id = current_user.id
    log_prefix = f"[API:Admin:{admin_id}:UpdateUserRole:{user_id}]"

    data = request.get_json()
    if not data or 'role_id' not in data:
        logging.warning(f"{log_prefix} Missing 'role_id' in request body.")
        return jsonify({'error': "Missing 'role_id' in request body."}), 400

    try:
        new_role_id = int(data['role_id'])
    except (ValueError, TypeError):
        logging.warning(f"{log_prefix} Invalid 'role_id' format: {data['role_id']}")
        return jsonify({'error': "Invalid 'role_id' format, must be an integer."}), 400


    try:
        # Call management service
        admin_management_service.update_user_role_admin(user_id, new_role_id, admin_id)
        return jsonify({'message': 'User role updated successfully.'}), 200
    except AdminServiceError as ase:
        # Handle specific errors from the service (user not found, role not found, self-update)
        logging.error(f"{log_prefix} Failed to update role: {ase}")
        status_code = 404 if "not found" in str(ase).lower() else 403 if "cannot change their own" in str(ase).lower() else 400
        return jsonify({'error': str(ase)}), status_code
    except Exception as e:
        # Handle unexpected errors
        logging.error(f"{log_prefix} Unexpected error updating role: {e}", exc_info=True)
        return jsonify({'error': 'Failed to update role due to an internal error.'}), 500

# --- Template Workflow Endpoints ---

# --- ADDED: Template Workflow Create Endpoint ---
@admin_bp.route('/template-workflows', methods=['POST'])
@admin_required
@permission_required('manage_workflow_templates')
@limiter.limit("20 per minute")
def create_template_workflow_api():
    """
    API endpoint for admins to create a new template workflow.
    Expects JSON payload: {"title": "...", "prompt_text": "...", "language": "...", "color": "..."}
    """
    admin_id = current_user.id
    log_prefix = f"[API:Admin:{admin_id}:CreateTemplateWorkflow]"

    data = request.get_json()
    if not data:
        logging.warning(f"{log_prefix} Received empty request body.")
        return jsonify({'error': 'Request body must be JSON.'}), 400

    title = data.get('title')
    prompt_text = data.get('prompt_text')
    language = data.get('language') # Can be empty string or null
    color = data.get('color', '#ffffff') # Default to white if missing

    if not title or not prompt_text:
        logging.warning(f"{log_prefix} Missing title or prompt_text in request.")
        return jsonify({'error': 'Missing title or prompt_text in request body.'}), 400


    try:
        new_template = admin_management_service.add_template_prompt(
            title=title,
            prompt_text=prompt_text,
            language=language or None, # Convert empty string to None
            color=color or '#ffffff' # Ensure default if empty
        )
        if new_template:
            logging.debug(f"{log_prefix} Successfully created template workflow.")
            # Return the created object
            return jsonify({
                'message': 'Template workflow created successfully.',
                'template': {
                    'id': new_template.id,
                    'title': new_template.title,
                    'prompt_text': new_template.prompt_text,
                    'language': new_template.language,
                    'color': new_template.color
                }
            }), 201 # HTTP 201 Created
        else:
            # Should be caught by service layer, but handle defensively
            logging.error(f"{log_prefix} Creation failed (service returned None).")
            return jsonify({'error': 'Failed to create template workflow.'}), 500
    except AdminServiceError as ase:
        logging.error(f"{log_prefix} Failed to create template workflow: {ase}")
        return jsonify({'error': str(ase)}), 400 # Bad Request for validation errors
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error creating template workflow: {e}", exc_info=True)
        return jsonify({'error': 'Failed to create template workflow due to an internal error.'}), 500
# --- END ADDED ---

@admin_bp.route('/template-workflows/<int:prompt_id>', methods=['PUT'])
@admin_required
@permission_required('manage_workflow_templates')
@limiter.limit("20 per minute")
def update_template_workflow_api(prompt_id):
    """
    API endpoint for admins to update an existing template workflow.
    Expects JSON payload: {"title": "...", "prompt_text": "...", "language": "...", "color": "..."}
    """
    admin_id = current_user.id
    log_prefix = f"[API:Admin:{admin_id}:UpdateTemplateWorkflow:{prompt_id}]"

    data = request.get_json()
    if not data:
        logging.warning(f"{log_prefix} Received empty request body.")
        return jsonify({'error': 'Request body must be JSON.'}), 400

    title = data.get('title')
    prompt_text = data.get('prompt_text')
    language = data.get('language') # Can be empty string or null
    color = data.get('color', '#ffffff') # Default to white if missing

    if not title or not prompt_text:
        logging.warning(f"{log_prefix} Missing title or prompt_text in request.")
        return jsonify({'error': 'Missing title or prompt_text in request body.'}), 400


    try:
        success = admin_management_service.update_template_prompt(
            prompt_id=prompt_id,
            title=title,
            prompt_text=prompt_text,
            language=language or None, # Convert empty string to None
            color=color or '#ffffff' # Ensure default if empty
        )
        if success:
            logging.debug(f"{log_prefix} Successfully updated template workflow.")
            return jsonify({'message': 'Template workflow updated successfully.'}), 200
        else:
            # Service layer should raise specific error if not found
            logging.error(f"{log_prefix} Update failed (service returned False).")
            return jsonify({'error': 'Failed to update template workflow.'}), 500
    except AdminServiceError as ase:
        # Handle specific errors from the service (e.g., not found)
        logging.error(f"{log_prefix} Failed to update template workflow: {ase}")
        status_code = 404 if "not found" in str(ase).lower() else 400
        return jsonify({'error': str(ase)}), status_code
    except Exception as e:
        # Handle unexpected errors
        logging.error(f"{log_prefix} Unexpected error updating template workflow: {e}", exc_info=True)
        return jsonify({'error': 'Failed to update template workflow due to an internal error.'}), 500
 
@admin_bp.route('/pricing', methods=['GET', 'POST'])
@admin_required
@limiter.limit("30 per minute")
def manage_pricing():
    """API endpoint to get or update pricing information."""
    log_prefix = f"[API:Admin:Pricing:User:{current_user.id}]"

    if request.method == 'POST':
        data = request.get_json()
        if not data:
            return jsonify(error="Invalid JSON payload"), 400
        try:
            if {'item_type', 'item_key', 'price'} <= set(data):
                pricing_service.update_price(data['item_type'], data['item_key'], data['price'])
            else:
                pricing_service.update_prices(data)
            return jsonify(success=True, message="Pricing updated successfully.")
        except PricingServiceError as e:
            logging.error(f"{log_prefix} Error updating pricing: {e}", exc_info=True)
            return jsonify(error=str(e)), 500
        except Exception as e:
            logging.error(f"{log_prefix} Unexpected error updating pricing: {e}", exc_info=True)
            return jsonify(error="An unexpected error occurred."), 500

    # GET request
    try:
        prices = pricing_service.get_all_prices()
        return jsonify(prices)
    except PricingServiceError as e:
        logging.error(f"{log_prefix} Error retrieving pricing: {e}", exc_info=True)
        return jsonify(error=str(e)), 500
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error retrieving pricing: {e}", exc_info=True)
        return jsonify(error="An unexpected error occurred while retrieving pricing."), 500


@admin_bp.route('/models/rename', methods=['POST'])
@admin_required
@limiter.limit("30 per minute")
def rename_catalog_model():
    """API endpoint to rename a catalog model display name (Models page)."""
    log_prefix = f"[API:Admin:Models:User:{current_user.id}]"
    data = request.get_json()
    if not data:
        return jsonify(error="Invalid JSON payload"), 400

    category = str(data.get('category') or '').strip()
    code = str(data.get('code') or '').strip()
    display_name = str(data.get('display_name') or '').strip()

    if category not in ('transcription', 'live', 'llm'):
        return jsonify(error="Invalid model category."), 400
    if not code or not display_name:
        return jsonify(error="Model code and display name are required."), 400
    if len(display_name) > 120:
        return jsonify(error="Display name must be 120 characters or fewer."), 400

    try:
        if category == 'llm':
            renamed = llm_catalog_model.rename_model(code, display_name)
        else:
            renamed = transcription_catalog_model.rename_model(code, display_name)
        if not renamed:
            return jsonify(error="Model not found in catalog."), 404
        return jsonify(success=True, message="Model renamed successfully.")
    except Exception as e:
        logging.error(f"{log_prefix} Unexpected error renaming model: {e}", exc_info=True)
        return jsonify(error="An unexpected error occurred while renaming the model."), 500
