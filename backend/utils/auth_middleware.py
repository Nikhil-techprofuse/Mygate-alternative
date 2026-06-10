from functools import wraps
from flask import request, jsonify, g
from ..supabase_client import get_admin_client

# Placeholder UUID used when a user has no society/flat assigned yet.
# Postgres accepts it as a valid UUID but no row will ever match it,
# so all queries return empty results rather than raising "invalid uuid: None".
_NULL_UUID = '00000000-0000-0000-0000-000000000000'


def has_flat():
    """Returns True if the current user has a real flat assigned."""
    return bool(g.flat_id) and g.flat_id != _NULL_UUID


def has_society():
    """Returns True if the current user has a real society assigned."""
    return bool(g.society_id) and g.society_id != _NULL_UUID

def require_auth(f):
    """Validates Supabase JWT from Authorization: Bearer <token> header."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing or invalid Authorization header'}), 401
        token = auth_header.split(' ', 1)[1]
        try:
            sb = get_admin_client()
            user_resp = sb.auth.get_user(token)
            if not user_resp or not user_resp.user:
                return jsonify({'error': 'Invalid or expired token'}), 401
            # Load profile + role
            profile = (
                sb.table('user_profiles')
                .select('*')
                .eq('id', user_resp.user.id)
                .single()
                .execute()
            )
            g.user_id    = user_resp.user.id
            g.profile    = profile.data if profile.data else {}
            g.role       = g.profile.get('role', '')
            g.society_id = g.profile.get('society_id') or _NULL_UUID
            g.flat_id    = g.profile.get('flat_id')    or _NULL_UUID
        except Exception as e:
            return jsonify({'error': 'Token validation failed', 'detail': str(e)}), 401
        return f(*args, **kwargs)
    return decorated


def require_role(*roles):
    """Role-based access: use after @require_auth."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if g.role not in roles:
                return jsonify({'error': f'Access denied. Required: {list(roles)}'}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator
