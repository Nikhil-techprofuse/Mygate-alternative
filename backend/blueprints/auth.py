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
        if phone:
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


@auth_bp.post('/magic-link')
def magic_link():
    """Trigger Magic Link email login for guards."""
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    if not email:
        return jsonify({'error': 'email is required'}), 400

    try:
        sb = get_admin_client()
        sb.auth.sign_in_with_otp({
            'email': email,
            'options': {
                'email_redirect_to': request.host_url + 'guard'
            }
        })
        return jsonify({'message': 'Check your email for login link!'})
    except Exception as e:
        return jsonify({'error': 'Failed to send magic link', 'detail': str(e)}), 500


@auth_bp.post('/verify-session')
def verify_session():
    """Verify a Supabase session (e.g. from Google OAuth / Magic Link) and return roles/user profile."""
    data = request.get_json(silent=True) or {}
    token = data.get('access_token')
    if not token:
        return jsonify({'error': 'access_token required'}), 400
    try:
        sb = get_admin_client()
        user_resp = sb.auth.get_user(token)
        if not user_resp or not user_resp.user:
            return jsonify({'error': 'Invalid token'}), 401
        
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

        role = profile.get('role', '')
        
        # Check authorized_guards table if role is guard or profile does not exist yet (but they have an email)
        if (role == 'guard' or (not role and email)) and email != 'dev-guard@mygate.internal':
            # Live check against Google Group membership
            from ..utils.google_groups import is_email_in_google_group
            is_in_group = is_email_in_google_group(email)

            if not is_in_group:
                # If they are not in the Google Group, deactivate them in authorized_guards and block access
                try:
                    sb.table('authorized_guards').update({'active': False}).eq('email', email).execute()
                    sb.table('user_profiles').update({'is_active': False}).eq('id', user_id).execute()
                except Exception:
                    pass
                return jsonify({'error': 'Access revoked: Not a member of the authorized Google Group.'}), 403

            # If they are in the group, ensure they exist and are active in authorized_guards table
            try:
                guard_check = (
                    sb.table('authorized_guards')
                    .select('*')
                    .eq('email', email)
                    .maybe_single()
                    .execute()
                )
                guard_data = guard_check.data if guard_check else None
            except Exception as e:
                if 'authorized_guards' in str(e):
                    return jsonify({
                        'error': 'Database table authorized_guards is not configured.',
                        'detail': 'Please run the SQL Table Setup in your Supabase SQL Editor first.'
                    }), 500
                raise e

            if not guard_data:
                # Auto-provision new guard from Google Group
                try:
                    insert_res = sb.table('authorized_guards').insert({
                        'email': email,
                        'name': 'Google Group Guard',
                        'gate_id': 'GATE-A',
                        'active': True
                    }).execute()
                    guard_data = insert_res.data[0] if insert_res.data else None
                except Exception:
                    pass
            elif not guard_data.get('active'):
                # Reactivate if they were inactive but are now in the group
                try:
                    update_res = sb.table('authorized_guards').update({'active': True}).eq('email', email).execute()
                    guard_data = update_res.data[0] if update_res.data else guard_data
                except Exception:
                    pass

            if not guard_data or not guard_data.get('active'):
                return jsonify({'error': 'Access revoked: Not an active authorized guard.'}), 403

            # Auto-create profile if missing
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

        if not role:
            # Fallback for residents or other roles
            role = 'resident'

        return jsonify({
            'access_token':  token,
            'refresh_token': data.get('refresh_token'),
            'user_id':       user_id,
            'role':          role,
            'society_id':    profile.get('society_id'),
            'flat_id':       profile.get('flat_id'),
        })

    except Exception as e:
        return jsonify({'error': 'Session verification failed', 'detail': str(e)}), 400
