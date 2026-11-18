# app/api/access.py
"""Endpoints behind User Settings > Access: password & sign-in, team mode, sign-ups."""

import logging

from flask import Blueprint, jsonify, request
from flask_babel import gettext as _
from flask_login import current_user, login_required

from app.extensions import limiter
from app.services import access_service
from app.services.access_service import AccessError

access_bp = Blueprint('access', __name__, url_prefix='/api/access')
logger = logging.getLogger(__name__)

LIMIT = "20 per minute;100 per hour"


def _payload() -> dict:
    return request.get_json(silent=True) or {}


def _error(exc: AccessError):
    message = str(exc.message)
    body = {'error': message}
    if exc.field:
        body['errors'] = {exc.field: [message]}
    return jsonify(body), exc.status


def _fresh_user():
    """Reload the user so a change made earlier in this request is visible."""
    from app.models import user as user_model
    return user_model.get_user_by_id(current_user.id)


@access_bp.route('/password', methods=['POST'])
@login_required
@limiter.limit(LIMIT)
def set_password():
    """Give an account without a password its first password (turns sign-in on)."""
    data = _payload()
    try:
        access_service.set_first_password(
            _fresh_user(),
            data.get('password'),
            data.get('confirm_password'),
            username=data.get('username'),
            email=data.get('email'),
        )
    except AccessError as exc:
        return _error(exc)
    logger.info("[API:Access] User %s set a password.", current_user.id)
    return jsonify({'message': _("Password set. You'll need it the next time you sign in.")}), 200


@access_bp.route('/password', methods=['DELETE'])
@login_required
@limiter.limit(LIMIT)
def remove_password():
    """Turn sign-in off (personal mode only)."""
    try:
        access_service.remove_owner_password(_fresh_user(), _payload().get('current_password'))
    except AccessError as exc:
        return _error(exc)
    return jsonify({'message': _('Sign-in is off. Transcriber now opens without a login.')}), 200


@access_bp.route('/team-mode', methods=['POST'])
@login_required
@limiter.limit(LIMIT)
def change_team_mode():
    """Turn team mode on ({"enabled": true, ...}) or off ({"enabled": false, "current_password": ...})."""
    data = _payload()
    user = _fresh_user()
    try:
        if data.get('enabled') is True:
            access_service.enable_team_mode(
                user,
                allow_registration=bool(data.get('allow_registration', True)),
                password=data.get('password'),
                confirm=data.get('confirm_password'),
                username=data.get('username'),
                email=data.get('email'),
            )
            return jsonify({'message': _("Team mode is on. You're the admin.")}), 200
        if data.get('enabled') is False:
            access_service.disable_team_mode(user, data.get('current_password'))
            return jsonify({'message': _('Personal mode is on. Only you can use Transcriber now.')}), 200
    except AccessError as exc:
        return _error(exc)
    return jsonify({'error': _('Missing "enabled" (true or false).')}), 400


@access_bp.route('/registration', methods=['POST'])
@login_required
@limiter.limit(LIMIT)
def change_registration():
    """Turn team-mode sign-ups on or off."""
    allowed = _payload().get('allowed')
    if not isinstance(allowed, bool):
        return jsonify({'error': _('Missing "allowed" (true or false).')}), 400
    try:
        access_service.set_registration_allowed(_fresh_user(), allowed)
    except AccessError as exc:
        return _error(exc)
    message = _('New sign-ups are on.') if allowed else _('New sign-ups are off.')
    return jsonify({'message': message}), 200
