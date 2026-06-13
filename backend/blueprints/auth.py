import os
import re
import psycopg2
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

    # ── Migrate admin-created profile if it exists ────────────────────────────
    if phone:
        try:
            # Check if there is an existing profile with same phone but different id
            dummy_q = (
                sb.table('user_profiles')
                .select('id, role, society_id, flat_id, full_name')
                .eq('phone', phone)
                .neq('id', user_id)
                .maybe_single()
                .execute()
            )
            dummy_profile = dummy_q.data if dummy_q else None
            if dummy_profile:
                dummy_id = dummy_profile['id']
                db_pwd = os.getenv('SUPABASE_DB_PASSWORD') or 'Lq5RnKwYdmZJrE2'
                supabase_url = os.getenv('SUPABASE_URL', 'https://olkudsuwbggebcdqpwfg.supabase.co')
                match = re.search(r"https?://([^.]+)\.supabase\.co", supabase_url)
                db_host = f"db.{match.group(1)}.supabase.co" if match else 'db.olkudsuwbggebcdqpwfg.supabase.co'
                
                conn = psycopg2.connect(
                    host=db_host,
                    port=5432,
                    dbname='postgres',
                    user='postgres',
                    password=db_pwd,
                    sslmode='require',
                    connect_timeout=15,
                )
                try:
                    cur = conn.cursor()
                    # Delete any user_profile already created for user_id to prevent primary key conflict
                    cur.execute("DELETE FROM user_profiles WHERE id = %s", (user_id,))
                    
                    # Update all referencing tables
                    cur.execute("UPDATE guard_gate_assignments SET guard_id = %s WHERE guard_id = %s", (user_id, dummy_id))
                    cur.execute("UPDATE gate_patrol_logs SET guard_id = %s WHERE guard_id = %s", (user_id, dummy_id))
                    cur.execute("UPDATE gate_chat_messages SET sender_id = %s WHERE sender_id = %s", (user_id, dummy_id))
                    cur.execute("UPDATE visitor_logs SET guard_id = %s WHERE guard_id = %s", (user_id, dummy_id))
                    cur.execute("UPDATE visitor_otps SET created_by = %s WHERE created_by = %s", (user_id, dummy_id))
                    cur.execute("UPDATE vehicles SET owner_id = %s WHERE owner_id = %s", (user_id, dummy_id))
                    cur.execute("UPDATE vehicle_entry_logs SET guard_id = %s WHERE guard_id = %s", (user_id, dummy_id))
                    cur.execute("UPDATE vehicle_disputes SET guard_id = %s WHERE guard_id = %s", (user_id, dummy_id))
                    cur.execute("UPDATE deliveries SET guard_id = %s WHERE guard_id = %s", (user_id, dummy_id))
                    cur.execute("UPDATE helper_flat_links SET resident_id = %s WHERE resident_id = %s", (user_id, dummy_id))
                    cur.execute("UPDATE helper_attendance SET guard_id = %s WHERE guard_id = %s", (user_id, dummy_id))
                    cur.execute("UPDATE helper_ratings SET resident_id = %s WHERE resident_id = %s", (user_id, dummy_id))
                    cur.execute("UPDATE kids_checkout_events SET guard_id = %s WHERE guard_id = %s", (user_id, dummy_id))
                    cur.execute("UPDATE emergency_contacts SET resident_id = %s WHERE resident_id = %s", (user_id, dummy_id))
                    cur.execute("UPDATE security_alerts SET triggered_by = %s WHERE triggered_by = %s", (user_id, dummy_id))
                    cur.execute("UPDATE security_alerts SET guard_acknowledged_by = %s WHERE guard_acknowledged_by = %s", (user_id, dummy_id))
                    cur.execute("UPDATE admin_broadcasts SET sent_by = %s WHERE sent_by = %s", (user_id, dummy_id))
                    cur.execute("UPDATE notices SET posted_by = %s WHERE posted_by = %s", (user_id, dummy_id))
                    cur.execute("UPDATE notice_acknowledgments SET resident_id = %s WHERE resident_id = %s", (user_id, dummy_id))
                    cur.execute("UPDATE polls SET created_by = %s WHERE created_by = %s", (user_id, dummy_id))
                    cur.execute("UPDATE poll_votes SET voter_id = %s WHERE voter_id = %s", (user_id, dummy_id))
                    cur.execute("UPDATE events SET created_by = %s WHERE created_by = %s", (user_id, dummy_id))
                    cur.execute("UPDATE event_rsvp SET resident_id = %s WHERE resident_id = %s", (user_id, dummy_id))
                    cur.execute("UPDATE forum_threads SET created_by = %s WHERE created_by = %s", (user_id, dummy_id))
                    cur.execute("UPDATE forum_replies SET posted_by = %s WHERE posted_by = %s", (user_id, dummy_id))
                    cur.execute("UPDATE society_documents SET uploaded_by = %s WHERE uploaded_by = %s", (user_id, dummy_id))
                    cur.execute("UPDATE personal_documents SET uploaded_by = %s WHERE uploaded_by = %s", (user_id, dummy_id))
                    cur.execute("UPDATE payments SET paid_by = %s WHERE paid_by = %s", (user_id, dummy_id))
                    cur.execute("UPDATE expenses SET recorded_by = %s WHERE recorded_by = %s", (user_id, dummy_id))
                    cur.execute("UPDATE helpdesk_tickets SET raised_by = %s WHERE raised_by = %s", (user_id, dummy_id))
                    cur.execute("UPDATE helpdesk_tickets SET assigned_to = %s WHERE assigned_to = %s", (user_id, dummy_id))
                    cur.execute("UPDATE ticket_updates SET updated_by = %s WHERE updated_by = %s", (user_id, dummy_id))
                    cur.execute("UPDATE ticket_attachments SET uploaded_by = %s WHERE uploaded_by = %s", (user_id, dummy_id))
                    cur.execute("UPDATE bookings SET booked_by = %s WHERE booked_by = %s", (user_id, dummy_id))
                    cur.execute("UPDATE staff_profiles SET user_id = %s WHERE user_id = %s", (user_id, dummy_id))
                    cur.execute("UPDATE staff_attendance SET marked_by = %s WHERE marked_by = %s", (user_id, dummy_id))
                    cur.execute("UPDATE leave_requests SET reviewed_by = %s WHERE reviewed_by = %s", (user_id, dummy_id))
                    
                    # Update user_profiles.id
                    cur.execute("UPDATE user_profiles SET id = %s WHERE id = %s", (user_id, dummy_id))
                    
                    # Clean up dummy user in auth.users
                    cur.execute("DELETE FROM auth.users WHERE id = %s", (dummy_id,))
                    
                    conn.commit()
                    cur.close()
                except Exception as e:
                    conn.rollback()
                    current_app.logger.error(f"Migration transaction failed: {e}")
                finally:
                    conn.close()
        except Exception as e:
            current_app.logger.error(f"Failed to migrate profile: {e}")

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
    data = profile.data if profile.data else g.profile
    if data:
        full_name = data.get('full_name')
        flat_id = data.get('flat_id')
        if (not full_name or full_name == 'Resident User') and flat_id:
            try:
                # Query user_profiles for any resident or tenant profile assigned to the same flat_id
                real_residents = (
                    sb.table('user_profiles')
                    .select('full_name')
                    .eq('flat_id', flat_id)
                    .neq('id', g.user_id)
                    .in_('role', ['resident', 'tenant', 'committee_member'])
                    .execute()
                )
                if real_residents and real_residents.data:
                    for r in real_residents.data:
                        name = (r.get('full_name') or '').strip()
                        if name and name != 'Resident User':
                            data['full_name'] = name
                            break
            except Exception as e:
                current_app.logger.error(f"Error querying real resident name for bypass: {e}")
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


@auth_bp.post('/select-flat')
@require_auth
def select_flat():
    """Set the current user's flat assignment from admin-created flats."""
    data = request.get_json(silent=True) or {}
    flat_id = data.get('flat_id')
    if not flat_id:
        return jsonify({'error': 'flat_id is required'}), 400

    sb = get_admin_client()
    flat = (
        sb.table('flats')
        .select('id, society_id')
        .eq('id', flat_id)
        .eq('society_id', g.society_id)
        .limit(1)
        .execute()
    )
    if not flat.data:
        return jsonify({'error': 'Flat not found in your society'}), 404

    updated = (
        sb.table('user_profiles')
        .update({'flat_id': flat_id})
        .eq('id', g.user_id)
        .execute()
    )
    return jsonify(updated.data[0] if updated.data else {'updated': True})


@auth_bp.get('/resident-flats')
@require_auth
def resident_flats():
    """Return buildings+flats that have at least one registered resident.
    Scopes flats by society (via flats.society_id) then checks user_profiles
    without re-filtering by society so admin-created profiles always appear."""
    sb = get_admin_client()

    # Step 1: all flats in this society with building info
    all_flats_q = (
        sb.table('flats')
        .select('id, flat_number, building_id, buildings(id, name)')
        .eq('society_id', g.society_id)
        .execute()
    )
    all_flats = all_flats_q.data or []
    if not all_flats:
        return jsonify([])

    all_flat_ids = [f['id'] for f in all_flats]

    # Step 2: which of those flat_ids have at least one resident profile
    # (no society_id filter here — admin-created profiles may have different mapping)
    # Supabase .in_() max 1000; chunk if needed
    occupied = set()
    chunk_size = 200
    for i in range(0, len(all_flat_ids), chunk_size):
        chunk = all_flat_ids[i:i+chunk_size]
        rows = (
            sb.table('user_profiles')
            .select('flat_id')
            .in_('flat_id', chunk)
            .in_('role', ['resident', 'tenant', 'committee_member'])
            .execute()
        )
        for r in (rows.data or []):
            if r.get('flat_id'):
                occupied.add(r['flat_id'])

    # Step 3: group occupied flats by building
    buildings = {}
    for f in all_flats:
        if f['id'] not in occupied:
            continue
        b = f.get('buildings') or {}
        bid = b.get('id') or f['building_id']
        if bid not in buildings:
            buildings[bid] = {'id': bid, 'name': b.get('name', '—'), 'flats': []}
        buildings[bid]['flats'].append({'id': f['id'], 'flat_number': f['flat_number']})

    result = sorted(buildings.values(), key=lambda x: x['name'])
    for bldg in result:
        bldg['flats'].sort(key=lambda x: x['flat_number'])
    return jsonify(result)
