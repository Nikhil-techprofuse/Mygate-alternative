from flask import Blueprint, request, jsonify, g, current_app
from ..supabase_client import get_admin_client
from ..utils.auth_middleware import require_auth

auth_bp = Blueprint('auth', __name__)

# Internal password used only for dev bypass accounts — never exposed to users
_DEV_BYPASS_PWD = 'mg-dev-bypass-internal-9x7z!'


def _dev_accounts() -> dict:
    """Returns {phone: (email, role)} for all configured dev accounts."""
    cfg = current_app.config
    accounts = {}
    if cfg.get('DEV_ADMIN_PHONE'):
        accounts[cfg['DEV_ADMIN_PHONE']] = ('dev-admin@mygate.internal',    'super_admin')
    if cfg.get('DEV_GUARD_PHONE'):
        accounts[cfg['DEV_GUARD_PHONE']] = ('dev-guard@mygate.internal',    'guard')
    if cfg.get('DEV_RESIDENT_PHONE'):
        accounts[cfg['DEV_RESIDENT_PHONE']] = ('dev-resident@mygate.internal', 'resident')
    return accounts


def _dev_otp_for(phone: str) -> str:
    cfg = current_app.config
    mapping = {
        cfg.get('DEV_ADMIN_PHONE'):    cfg.get('DEV_ADMIN_OTP', ''),
        cfg.get('DEV_GUARD_PHONE'):    cfg.get('DEV_GUARD_OTP', ''),
        cfg.get('DEV_RESIDENT_PHONE'): cfg.get('DEV_RESIDENT_OTP', ''),
    }
    return mapping.get(phone, '')


@auth_bp.post('/send-otp')
def send_otp():
    """Trigger Supabase phone OTP for login."""
    data = request.get_json(silent=True) or {}
    phone = (data.get('phone') or '').strip()
    if not phone:
        return jsonify({'error': 'phone is required'}), 400
    if not phone.startswith('+') or len(phone) < 8:
        return jsonify({'error': 'phone must be in E.164 format e.g. +919876543210'}), 400

    # ── Dev bypass: any registered dev phone ──────────────────────────────────
    otp = _dev_otp_for(phone)
    if otp:
        return jsonify({'message': f'Dev mode — use OTP {otp} to login'})

    try:
        sb = get_admin_client()
        sb.auth.sign_in_with_otp({'phone': phone})
        return jsonify({'message': 'OTP sent successfully'})
    except Exception as e:
        return jsonify({'error': 'Failed to send OTP', 'detail': str(e)}), 500


@auth_bp.post('/verify-otp')
def verify_otp():
    """Verify OTP and return Supabase session JWT."""
    data = request.get_json(silent=True) or {}
    phone = (data.get('phone') or '').strip()
    token = (data.get('token') or '').strip()
    if not phone or not token:
        return jsonify({'error': 'phone and token are required'}), 400

    # ── Dev bypass ────────────────────────────────────────────────────────────
    expected_otp = _dev_otp_for(phone)
    if expected_otp and token == expected_otp:
        return _dev_login(phone)

    try:
        sb = get_admin_client()
        session = sb.auth.verify_otp({'phone': phone, 'token': token, 'type': 'sms'})
        if not session or not session.session:
            return jsonify({'error': 'Invalid OTP'}), 401
        return _build_session_response(session)
    except Exception as e:
        return jsonify({'error': 'OTP verification failed', 'detail': str(e)}), 500


def _dev_login(phone: str):
    """
    Dev-only bypass: creates a role-specific internal email account and signs in
    with email+password to get a real Supabase JWT — no SMS needed.
    """
    accounts  = _dev_accounts()
    dev_email, dev_role = accounts.get(phone, ('dev-admin@mygate.internal', 'super_admin'))
    sb = get_admin_client()

    # Step 1: ensure the dev account exists in Supabase Auth
    try:
        sb.auth.admin.create_user({
            'email':         dev_email,
            'password':      _DEV_BYPASS_PWD,
            'email_confirm': True,
        })
    except Exception:
        # Already exists — ensure password is correct
        try:
            all_users = sb.auth.admin.list_users()
            user_list = all_users if isinstance(all_users, list) else getattr(all_users, 'users', [])
            existing  = next((u for u in user_list if getattr(u, 'email', '') == dev_email), None)
            if existing:
                sb.auth.admin.update_user_by_id(existing.id, {
                    'password':      _DEV_BYPASS_PWD,
                    'email_confirm': True,
                })
        except Exception:
            pass

    # Step 2: sign in to get a real JWT
    try:
        session = sb.auth.sign_in_with_password({
            'email':    dev_email,
            'password': _DEV_BYPASS_PWD,
        })
    except Exception as e:
        return jsonify({'error': 'Dev login failed — sign in error', 'detail': str(e)}), 500

    if not session or not session.session:
        return jsonify({'error': 'Dev login failed — no session returned'}), 500

    return _build_session_response(session, default_role=dev_role)


def _build_session_response(session, default_role: str = 'super_admin'):
    """Upsert user profile and return JWT payload."""
    sb      = get_admin_client()
    user_id = session.user.id
    phone   = getattr(session.user, 'phone', None)

    try:
        existing = (
            sb.table('user_profiles')
            .select('id, role, society_id, flat_id, full_name')
            .eq('id', user_id)
            .maybe_single()
            .execute()
        )
        profile = (existing.data if existing else None) or {}
    except Exception:
        profile = {}

    if not profile:
        new_row = {'id': user_id, 'role': default_role}
        if phone:  # don't insert empty phone — unique constraint would conflict
            new_row['phone'] = phone
        sb.table('user_profiles').insert(new_row).execute()
        profile = {'role': default_role}

    return jsonify({
        'access_token':  session.session.access_token,
        'refresh_token': session.session.refresh_token,
        'user_id':       user_id,
        'role':          profile.get('role'),
        'society_id':    profile.get('society_id'),
        'flat_id':       profile.get('flat_id'),
    })


@auth_bp.post('/refresh')
def refresh_token():
    """Refresh an expired JWT using the refresh token."""
    data = request.get_json(silent=True) or {}
    refresh = (data.get('refresh_token') or '').strip()
    if not refresh:
        return jsonify({'error': 'refresh_token is required'}), 400
    try:
        sb = get_admin_client()
        session = sb.auth.refresh_session(refresh)
        return jsonify({
            'access_token':  session.session.access_token,
            'refresh_token': session.session.refresh_token,
        })
    except Exception as e:
        return jsonify({'error': 'Token refresh failed', 'detail': str(e)}), 401


@auth_bp.get('/me')
@require_auth
def me():
    """Return current user profile + role + flat number."""
    sb = get_admin_client()
    profile = (
        sb.table('user_profiles')
        .select('*, flats(flat_number, building_id, buildings(name))')
        .eq('id', g.user_id)
        .single()
        .execute()
    )
    return jsonify(profile.data if profile.data else g.profile)


@auth_bp.patch('/me')
@require_auth
def update_me():
    """Update own profile (name, email)."""
    data = request.get_json(silent=True) or {}
    allowed = ['full_name', 'email']
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({'error': 'No valid fields to update'}), 400
    sb = get_admin_client()
    result = (
        sb.table('user_profiles')
        .update(updates)
        .eq('id', g.user_id)
        .execute()
    )
    return jsonify(result.data[0] if result.data else {})
