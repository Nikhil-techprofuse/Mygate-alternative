from functools import wraps
from flask import request, jsonify, g
from ..supabase_client import get_admin_client

# Placeholder UUID used when a user has no society/flat assigned yet.
_NULL_UUID = '00000000-0000-0000-0000-000000000000'


def has_flat():
    """Returns True if the current user has a real flat assigned."""
    return bool(g.flat_id) and g.flat_id != _NULL_UUID


def has_society():
    """Returns True if the current user has a real society assigned."""
    return bool(g.society_id) and g.society_id != _NULL_UUID


def require_auth(f):
    """Validates Supabase JWT from Authorization: Bearer <token> header and performs role-specific checks."""
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
            
            user_id = user_resp.user.id
            email = getattr(user_resp.user, 'email', None)

            # Load user profile
            try:
                profile_res = (
                    sb.table('user_profiles')
                    .select('*')
                    .eq('id', user_id)
                    .single()
                    .execute()
                )
                profile = profile_res.data if profile_res else {}
            except Exception:
                profile = {}

            # Check if user profile is explicitly deactivated
            if profile and profile.get('is_active') is False:
                return jsonify({'error': 'Access revoked: User account is inactive.'}), 403

            role = profile.get('role', '')

            # Check authorized_guards table if role is guard or profile does not exist yet (but they have an email)
            if (role == 'guard' or (not role and email)) and email != 'dev-guard@mygate.internal':
                try:
                    guard_check = (
                        sb.table('authorized_guards')
                        .select('*')
                        .eq('email', email)
                        .maybe_single()
                        .execute()
                    )
                    guard_data = guard_check.data if guard_check else None
                except Exception as db_err:
                    guard_data = None
                    if 'authorized_guards' in str(db_err) and role == 'guard':
                        return jsonify({
                            'error': 'Database table authorized_guards is not configured.',
                            'detail': 'Please run the SQL Table Setup in your Supabase SQL Editor first.'
                        }), 500

                if role == 'guard' or (guard_data and guard_data.get('active')):
                    if not guard_data or not guard_data.get('active'):
                        return jsonify({'error': 'Access revoked: Not an active authorized guard.'}), 403

                    # If they are active and profile doesn't exist, auto-create it
                    if not profile:
                        society_id = '02b53b8b-7b77-4b1e-9cc7-4a31cd9cce39' # Default society ID
                        new_profile = {
                            'id': user_id,
                            'role': 'guard',
                            'full_name': guard_data.get('name') or 'Gate Guard',
                            'society_id': society_id,
                            'is_active': True
                        }
                        sb.table('user_profiles').insert(new_profile).execute()
                        profile = new_profile
                        role = 'guard'

                    # Update last login timestamp in authorized_guards
                    try:
                        from datetime import datetime, timezone
                        sb.table('authorized_guards').update({
                            'last_login': datetime.now(timezone.utc).isoformat()
                        }).eq('email', email).execute()
                    except Exception:
                        pass

            g.user_id    = user_id
            g.profile    = profile
            g.role       = role or profile.get('role', '')
            g.society_id = profile.get('society_id') or _NULL_UUID
            g.flat_id    = profile.get('flat_id')    or _NULL_UUID
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
