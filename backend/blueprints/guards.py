from flask import Blueprint, request, jsonify, g
from ..supabase_client import get_admin_client
from ..utils.auth_middleware import require_auth, require_role
from .visitors import verify_visitor_otp_internal
from .domestic_help import lookup_helper_by_passcode

guards_bp = Blueprint('guards', __name__)


@guards_bp.post('/verify-code')
@require_auth
@require_role('guard')
def verify_code():
    """Unified lookup: visitor OTP (6 digits) or helper passcode (4–6 digits)."""
    data = request.get_json(silent=True) or {}
    code = (data.get('code') or '').strip()

    if not code or not code.isdigit():
        return jsonify({'error': 'A numeric code is required'}), 400
    if len(code) not in (4, 6):
        return jsonify({'error': 'Code must be 4 or 6 digits'}), 400

    sb = get_admin_client()
    gate_id = data.get('gate_id') or g.profile.get('gate_id')

    if len(code) == 6:
        visitor_result = verify_visitor_otp_internal(
            sb, g.society_id, g.user_id, code, gate_id=gate_id,
        )
        if visitor_result['success']:
            return jsonify({'type': 'visitor', 'data': visitor_result['data']})
        if not visitor_result.get('not_found'):
            return jsonify({'error': visitor_result['error']}), visitor_result['status']

    helper_result = lookup_helper_by_passcode(sb, g.society_id, code)
    if helper_result['success']:
        return jsonify({'type': 'helper', 'data': helper_result['data']})
    if helper_result.get('blacklisted'):
        return jsonify({'error': helper_result['error'], 'type': 'helper', 'data': helper_result['data']}), helper_result['status']

    return jsonify({
        'error': 'Invalid code. Not found in visitor OTPs or helper passcodes.',
    }), 404
