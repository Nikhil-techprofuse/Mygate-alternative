from flask import Blueprint, jsonify, g
from ..utils.auth_middleware import require_auth

notifications_bp = Blueprint('notifications', __name__)

@notifications_bp.get('/vapid-public-key')
def vapid_public_key():
    """Returns VAPID public key for Web Push subscription setup."""
    from flask import current_app
    key = current_app.config.get('VAPID_PUBLIC_KEY', '')
    return jsonify({'vapid_public_key': key})
