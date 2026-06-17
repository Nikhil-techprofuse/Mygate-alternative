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


def _dev_email_login(email: str):
    """
    Dev-only bypass for email login: ensures the test account exists,
    signs in, and builds the response.
    """
    sb = get_admin_client()
    try:
        sb.auth.admin.create_user({
            'email':         email,
            'password':      _DEV_BYPASS_PWD,
            'email_confirm': True,
        })
    except Exception:
        try:
            all_users = sb.auth.admin.list_users()
            user_list = all_users if isinstance(all_users, list) else getattr(all_users, 'users', [])
            existing  = next((u for u in user_list if getattr(u, 'email', '') == email), None)
            if existing:
                sb.auth.admin.update_user_by_id(existing.id, {
                    'password':      _DEV_BYPASS_PWD,
                    'email_confirm': True,
                })
        except Exception:
            pass

    try:
        session = sb.auth.sign_in_with_password({
            'email':    email,
            'password': _DEV_BYPASS_PWD,
        })
    except Exception as e:
        return jsonify({'error': 'Dev login failed — sign in error', 'detail': str(e)}), 500

    if not session or not session.session:
        return jsonify({'error': 'Dev login failed — no session returned'}), 500

    return _build_session_response(session, default_role='guard')



def _build_session_response(session, default_role: str = 'super_admin'):
    """Upsert user profile and return JWT payload."""
    sb      = get_admin_client()
    user_id = session.user.id
    phone   = getattr(session.user, 'phone', None)
    email   = getattr(session.user, 'email', None)

    # Dev bypass check
    dev_bypass = False
    try:
        from flask import current_app
        cfg = current_app.config
        dev_phones = [cfg.get('DEV_ADMIN_PHONE'), cfg.get('DEV_GUARD_PHONE'), cfg.get('DEV_RESIDENT_PHONE')]
        if phone in dev_phones or (email and email.endswith('@mygate.internal')):
            dev_bypass = True
    except Exception:
        pass

    try:
        existing = (
            sb.table('user_profiles')
            .select('id, role, society_id, flat_id, full_name, phone, email')
            .eq('id', user_id)
            .maybe_single()
            .execute()
        )
        profile = (existing.data if existing else None) or {}
    except Exception:
        profile = {}

    if not profile:
        # Check if there's a pre-registered resident with this phone number
        profile_to_link = None
        if phone:
            try:
                res = sb.table('user_profiles').select('*').eq('phone', phone).maybe_single().execute()
                if res and res.data:
                    profile_to_link = res.data
            except Exception:
                pass
        
        # If not found by phone, try email (for Google OAuth / email OTP)
        if not profile_to_link and email:
            try:
                res = sb.table('user_profiles').select('*').eq('email', email.lower().strip()).maybe_single().execute()
                if res and res.data:
                    profile_to_link = res.data
            except Exception:
                pass

        if profile_to_link:
            try:
                # Link the pre-registered profile to this logged-in auth user
                sb.table('user_profiles').update({'id': user_id}).eq('id', profile_to_link['id']).execute()
                profile = profile_to_link
                profile['id'] = user_id
            except Exception as e:
                # Fallback to copy fields if primary key update is blocked
                try:
                    sb.table('user_profiles').insert({
                        'id': user_id,
                        'role': profile_to_link.get('role', default_role),
                        'society_id': profile_to_link.get('society_id'),
                        'flat_id': profile_to_link.get('flat_id'),
                        'full_name': profile_to_link.get('full_name'),
                        'phone': phone,
                        'email': email
                    }).execute()
                    profile = {
                        'id': user_id,
                        'role': profile_to_link.get('role', default_role),
                        'society_id': profile_to_link.get('society_id'),
                        'flat_id': profile_to_link.get('flat_id'),
                        'full_name': profile_to_link.get('full_name'),
                        'phone': phone,
                        'email': email
                    }
                except Exception:
                    pass
        elif dev_bypass or default_role in ('super_admin', 'guard'):
            # Create a profile for dev accounts, admins, or guards
            society_id = '02b53b8b-7b77-4b1e-9cc7-4a31cd9cce39' # Default society ID
            new_row = {'id': user_id, 'role': default_role, 'society_id': society_id}
            if phone:
                new_row['phone'] = phone
            sb.table('user_profiles').insert(new_row).execute()
            profile = {'role': default_role, 'society_id': society_id}
        else:
            # Block login
            return jsonify({
                'error': 'Access denied: You are not registered as a resident in this society. Please contact the administrator.'
            }), 403

    elif not profile.get('society_id'):
        society_id = '02b53b8b-7b77-4b1e-9cc7-4a31cd9cce39' # Default society ID
        sb.table('user_profiles').update({'society_id': society_id}).eq('id', user_id).execute()
        profile['society_id'] = society_id

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
    data = profile.data if profile.data else g.profile
    if data and data.get('role') == 'guard':
        email = data.get('email')
        if not email:
            auth_header = request.headers.get('Authorization', '')
            parts = auth_header.split(' ', 1)
            if len(parts) > 1:
                try:
                    user_resp = sb.auth.get_user(parts[1])
                    email = getattr(user_resp.user, 'email', None) if user_resp and user_resp.user else None
                except Exception:
                    pass
        
        gate_id = 'GATE-A'
        if email:
            try:
                guard_check = sb.table('authorized_guards').select('gate_id').eq('email', email).maybe_single().execute()
                if guard_check and guard_check.data:
                    gate_id = guard_check.data.get('gate_id') or 'GATE-A'
            except Exception:
                pass
        
        data = dict(data)
        data['gate_id'] = gate_id
        if email:
            data['email'] = email
            
    return jsonify(data)


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
    """Trigger Email OTP login for guards."""
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    if not email:
        return jsonify({'error': 'email is required'}), 400

    # Dev bypass for sending
    if email == 'guard1@gmail.com':
        return jsonify({'message': 'Check your email for the OTP code! (Dev bypass active: use code 111111)'})

    try:
        sb = get_admin_client()
        sb.auth.sign_in_with_otp({
            'email': email,
            'options': {
                'email_redirect_to': request.host_url + 'guard'
            }
        })
        return jsonify({'message': 'Check your email for the OTP code!'})
    except Exception as e:
        return jsonify({'error': 'Failed to send email OTP', 'detail': str(e)}), 500


@auth_bp.post('/verify-email-otp')
def verify_email_otp():
    """Verify email OTP token and return session payload if Google Group authorized."""
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    token = (data.get('token') or '').strip()
    if not email or not token:
        return jsonify({'error': 'email and token are required'}), 400

    # Dev bypass for testing without actual email
    if email == 'guard1@gmail.com' and token == '111111':
        return _dev_email_login(email)

    try:
        sb = get_admin_client()
        # Verify email OTP (Supabase supports 'email' or 'magiclink' as type depending on config)
        try:
            session = sb.auth.verify_otp({'email': email, 'token': token, 'type': 'email'})
        except Exception:
            session = sb.auth.verify_otp({'email': email, 'token': token, 'type': 'magiclink'})

        if not session or not session.session:
            return jsonify({'error': 'Invalid or expired OTP'}), 401

        user_id = session.user.id
        
        # Check Google Group membership
        from ..utils.google_groups import is_email_in_google_group
        is_in_group = is_email_in_google_group(email)

        if not is_in_group:
            # Deactivate access
            try:
                sb.table('authorized_guards').update({'active': False}).eq('email', email).execute()
                sb.table('user_profiles').update({'is_active': False}).eq('id', user_id).execute()
            except Exception:
                pass
            return jsonify({'error': 'Access revoked: Not a member of the authorized Google Group.'}), 403

        # Ensure they are active in authorized_guards table
        try:
            guard_check = sb.table('authorized_guards').select('*').eq('email', email).maybe_single().execute()
            guard_data = guard_check.data if guard_check else None
        except Exception:
            guard_data = None

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
            # Reactivate
            try:
                update_res = sb.table('authorized_guards').update({'active': True}).eq('email', email).execute()
                guard_data = update_res.data[0] if update_res.data else guard_data
            except Exception:
                pass

        if not guard_data or not guard_data.get('active'):
            return jsonify({'error': 'Access revoked: Not an active authorized guard.'}), 403

        # Update last login timestamp
        try:
            from datetime import datetime, timezone
            sb.table('authorized_guards').update({
                'last_login': datetime.now(timezone.utc).isoformat()
            }).eq('email', email).execute()
        except Exception:
            pass

        return _build_session_response(session, default_role='guard')

    except Exception as e:
        return jsonify({'error': 'OTP verification failed', 'detail': str(e)}), 500



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


@auth_bp.get('/resident-flats')
@require_auth
def get_resident_flats():
    sb = get_admin_client()
    try:
        # Fetch buildings in the society
        b_res = sb.table('buildings').select('id, name').eq('society_id', g.society_id).execute()
        buildings = b_res.data if b_res else []
        if not buildings:
            return jsonify([])

        # Find all flat IDs that are referenced by active user_profiles in this society
        try:
            up_res = (
                sb.table('user_profiles')
                .select('flat_id')
                .not_.is_('flat_id', 'null')
                .eq('is_active', True)
                .eq('society_id', g.society_id)
                .execute()
            )
            profile_rows = up_res.data if up_res else []
            flat_ids = list({r['flat_id'] for r in profile_rows if r.get('flat_id')})
        except Exception:
            flat_ids = []

        if not flat_ids:
            # No occupied flats — return empty list per-building
            return jsonify([{'id': b['id'], 'name': b['name'], 'flats': []} for b in buildings])

        # Fetch only flats that are occupied
        f_res = sb.table('flats').select('id, flat_number, building_id').in_('id', flat_ids).execute()
        flats = f_res.data if f_res else []

        flats_by_b = {}
        for f in flats:
            bid = f['building_id']
            flats_by_b.setdefault(bid, []).append({'id': f['id'], 'flat_number': f['flat_number']})

        result = []
        for b in buildings:
            result.append({'id': b['id'], 'name': b['name'], 'flats': flats_by_b.get(b['id'], [])})

        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@auth_bp.get('/flat-resident')
@require_auth
def get_flat_resident():
    """Return the primary resident name for the user's selected flat."""
    sb = get_admin_client()
    flat_id = g.flat_id
    if not flat_id or flat_id == '00000000-0000-0000-0000-000000000000':
        return jsonify({'resident_name': None})
    try:
        resident = (
            sb.table('user_profiles')
            .select('full_name')
            .eq('flat_id', flat_id)
            .eq('society_id', g.society_id)
            .in_('role', ['resident', 'tenant', 'committee_member'])
            .eq('is_active', True)
            .neq('id', g.user_id)
            .order('created_at', desc=False)
            .limit(1)
            .execute()
        )
        name = resident.data[0]['full_name'] if resident.data else None
        return jsonify({'resident_name': name})
    except Exception:
        return jsonify({'resident_name': None})


@auth_bp.post('/select-flat')
@require_auth
def select_flat():
    data = request.get_json(silent=True) or {}
    flat_id = data.get('flat_id')
    if not flat_id:
        return jsonify({'error': 'flat_id is required'}), 400
    
    sb = get_admin_client()
    try:
        # Verify the flat exists and fetch its society_id
        flat_check = sb.table('flats').select('id, society_id').eq('id', flat_id).maybe_single().execute()
        if not flat_check.data:
            return jsonify({'error': 'Flat not found'}), 404
        
        society_id = flat_check.data['society_id']
        
        # Update user's profile with selected flat and its society
        sb.table('user_profiles').update({
            'flat_id': flat_id,
            'society_id': society_id
        }).eq('id', g.user_id).execute()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
