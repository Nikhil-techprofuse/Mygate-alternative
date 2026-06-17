from flask import Blueprint, request, jsonify, g
from ..supabase_client import get_admin_client
from ..utils.auth_middleware import require_auth, require_role

admin_bp = Blueprint('admin', __name__)

# ── Society setup ─────────────────────────────────────────────────────────────
@admin_bp.post('/society')
@require_auth
@require_role('super_admin')
def create_society():
    data = request.get_json(silent=True) or {}
    if not data.get('name'):
        return jsonify({'error': 'name required'}), 400
    sb = get_admin_client()
    result = sb.table('societies').insert({
        'name':    data['name'],
        'address': data.get('address'),
        'city':    data.get('city'),
        'state':   data.get('state'),
        'pincode': data.get('pincode'),
    }).execute()
    society = result.data[0]
    # Auto-link the creator's profile to this society
    sb.table('user_profiles').update({'society_id': society['id']}).eq('id', g.user_id).execute()
    return jsonify(society), 201

@admin_bp.get('/societies')
@require_auth
@require_role('super_admin', 'committee_member')
def list_societies():
    sb = get_admin_client()
    return jsonify(sb.table('societies').select('*').order('name').execute().data)

@admin_bp.get('/society/<society_id>')
@require_auth
@require_role('super_admin', 'committee_member')
def get_society(society_id):
    sb = get_admin_client()
    return jsonify(sb.table('societies').select('*').eq('id', society_id).single().execute().data)

@admin_bp.post('/buildings')
@require_auth
@require_role('super_admin', 'committee_member')
def create_building():
    data = request.get_json(silent=True) or {}
    if not data.get('name'):
        return jsonify({'error': 'name required'}), 400
    floors = int(data.get('floors') or 1)
    flats_per_floor = int(data.get('flats_per_floor') or 0)
    if floors < 1 or floors > 100:
        return jsonify({'error': 'floors must be 1–100'}), 400
    if flats_per_floor < 0 or flats_per_floor > 50:
        return jsonify({'error': 'flats_per_floor must be 0–50'}), 400

    sb = get_admin_client()
    result = sb.table('buildings').insert({
        'society_id': g.society_id,
        'name':       data['name'],
        'floors':     floors,
    }).execute()
    building = result.data[0]
    building_id = building['id']

    # Auto-generate flats if requested
    flats_created = 0
    if flats_per_floor > 0:
        flat_rows = []
        for floor in range(1, floors + 1):
            for unit in range(1, flats_per_floor + 1):
                flat_number = f"{floor}{unit:02d}"
                flat_rows.append({
                    'society_id':  g.society_id,
                    'building_id': building_id,
                    'flat_number': flat_number,
                    'floor':       floor,
                })
        for i in range(0, len(flat_rows), 50):
            batch = flat_rows[i:i+50]
            sb.table('flats').insert(batch).execute()
        flats_created = len(flat_rows)

    building['flats_created'] = flats_created
    return jsonify(building), 201

@admin_bp.get('/buildings')
@require_auth
def list_buildings():
    sb = get_admin_client()
    return jsonify(sb.table('buildings').select('*').eq('society_id', g.society_id).execute().data)

@admin_bp.delete('/buildings/<building_id>')
@require_auth
@require_role('super_admin', 'committee_member')
def delete_building(building_id):
    sb = get_admin_client()
    existing = sb.table('buildings').select('id').eq('id', building_id).eq('society_id', g.society_id).maybe_single().execute()
    if not existing.data:
        return jsonify({'error': 'Building not found'}), 404
    flats = sb.table('flats').select('id').eq('building_id', building_id).execute().data or []
    flat_ids = [f['id'] for f in flats]
    if flat_ids:
        for fid in flat_ids:
            sb.table('user_profiles').update({'flat_id': None}).eq('flat_id', fid).execute()
        sb.table('family_members').delete().in_('flat_id', flat_ids).execute()
    try:
        sb.table('flats').delete().eq('building_id', building_id).execute()
    except Exception:
        pass
    sb.table('buildings').delete().eq('id', building_id).execute()
    return jsonify({'deleted': True})

@admin_bp.post('/flats')
@require_auth
@require_role('super_admin', 'committee_member')
def create_flat():
    data = request.get_json(silent=True) or {}
    if not data.get('flat_number') or not data.get('building_id'):
        return jsonify({'error': 'flat_number and building_id required'}), 400
    sb = get_admin_client()
    result = sb.table('flats').insert({'society_id': g.society_id, 'building_id': data['building_id'], 'flat_number': data['flat_number'], 'floor': data.get('floor'), 'area_sqft': data.get('area_sqft'), 'max_cars': data.get('max_cars', 1), 'max_two_wheelers': data.get('max_two_wheelers', 1)}).execute()
    return jsonify(result.data[0]), 201

@admin_bp.get('/flats')
@require_auth
def list_flats():
    sb = get_admin_client()
    q = sb.table('flats').select('*, buildings(name)').eq('society_id', g.society_id)
    if request.args.get('building_id'):
        q = q.eq('building_id', request.args['building_id'])
    return jsonify(q.execute().data)

@admin_bp.get('/residents')
@require_auth
@require_role('super_admin', 'committee_member')
def list_residents():
    sb = get_admin_client()
    profiles = sb.table('user_profiles').select(
        'id, full_name, phone, role, flat_id, is_active, flats(flat_number, floor, building_id, buildings(name))'
    ).eq('society_id', g.society_id).in_('role', ['resident', 'tenant', 'committee_member']).execute().data or []

    family_rows = sb.table('family_members').select('flat_id, id').eq('society_id', g.society_id).eq('is_active', True).execute().data or []
    fam_count = {}
    for f in family_rows:
        fam_count[f['flat_id']] = fam_count.get(f['flat_id'], 0) + 1
    for p in profiles:
        p['family_count'] = fam_count.get(p.get('flat_id'), 0)
    return jsonify(profiles)


@admin_bp.post('/residents')
@require_auth
@require_role('super_admin', 'committee_member')
def add_resident():
    data = request.get_json(silent=True) or {}
    if not data.get('full_name'):
        return jsonify({'error': 'full_name is required'}), 400

    sb = get_admin_client()
    flat_id = _resolve_flat_id(sb, data)
    if isinstance(flat_id, tuple):
        return flat_id

    role = data.get('role', 'resident')
    if role not in ('resident', 'tenant', 'committee_member'):
        return jsonify({'error': 'Invalid role'}), 400

    # Prevent adding another resident to the same flat (if already occupied)
    try:
        existing_member = sb.table('user_profiles')\
            .select('id, full_name, role')\
            .eq('flat_id', flat_id)\
            .eq('society_id', g.society_id)\
            .in_('role', ['resident', 'tenant', 'committee_member'])\
            .eq('is_active', True)\
            .limit(1)\
            .execute()
        if existing_member.data:
            return jsonify({'error': 'Already resident exists in this flat', 'member': existing_member.data[0]}), 409
    except Exception as e:
        return jsonify({'error': f'Duplicate check failed: {str(e)}'}), 500

    phone = (data.get('phone') or '').strip() or None
    if phone:
        existing = sb.table('user_profiles').select('id').eq('phone', phone).limit(1).execute()
        if existing.data:
            return jsonify({'error': 'Phone number already registered'}), 409

    import uuid, psycopg2
    new_id = str(uuid.uuid4())
    conn = psycopg2.connect(
        host='db.olkudsuwbggebcdqpwfg.supabase.co', port=5432, dbname='postgres',
        user='postgres', password='Lq5RnKwYdmZJrE2',
        sslmode='require', connect_timeout=15,
    )
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO auth.users (id, email, role, aud, created_at, updated_at, confirmation_token, recovery_token) "
            "VALUES (%s, %s, 'authenticated', 'authenticated', NOW(), NOW(), '', '') ON CONFLICT (id) DO NOTHING",
            (new_id, f"resident-{new_id[:8]}@mygate-nologin.internal")
        )
        cur.execute(
            "INSERT INTO user_profiles (id, society_id, flat_id, full_name, phone, role, is_active) "
            "VALUES (%s, %s, %s, %s, %s, %s, TRUE) "
            "RETURNING id, full_name, phone, role, flat_id, society_id, is_active, created_at",
            (new_id, g.society_id, flat_id, data['full_name'], phone, role)
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'error': str(e)}), 500
    conn.close()

    return jsonify({
        'id': row[0], 'full_name': row[1], 'phone': row[2],
        'role': row[3], 'flat_id': row[4], 'society_id': row[5],
        'is_active': row[6], 'created_at': str(row[7])
    }), 201


def _resolve_flat_id(sb, data):
    if data.get('flat_id'):
        flat = sb.table('flats').select('id').eq('id', data['flat_id']).eq('society_id', g.society_id).limit(1).execute()
        if not flat.data:
            return jsonify({'error': 'Flat not found in this society'}), 404
        return data['flat_id']

    building_id  = data.get('building_id')
    floor        = data.get('floor')
    flat_number  = (data.get('flat_number') or '').strip()

    if not building_id:
        return jsonify({'error': 'building_id is required'}), 400
    if flat_number == '':
        return jsonify({'error': 'flat_number is required'}), 400

    bldg = sb.table('buildings').select('id, floors').eq('id', building_id).eq('society_id', g.society_id).limit(1).execute()
    if not bldg.data:
        return jsonify({'error': 'Building not found in this society'}), 404

    q = sb.table('flats').select('id').eq('building_id', building_id).eq('flat_number', flat_number).limit(1).execute()
    if q.data:
        return q.data[0]['id']

    result = sb.table('flats').insert({
        'society_id':  g.society_id,
        'building_id': building_id,
        'flat_number': flat_number,
        'floor':       int(floor) if floor is not None else None,
    }).execute()
    return result.data[0]['id']


@admin_bp.patch('/residents/<resident_id>')
@require_auth
@require_role('super_admin', 'committee_member')
def update_resident(resident_id):
    data = request.get_json(silent=True) or {}
    sb = get_admin_client()

    existing = sb.table('user_profiles').select('id').eq('id', resident_id).eq('society_id', g.society_id).limit(1).execute()
    if not existing.data:
        return jsonify({'error': 'Resident not found'}), 404

    if data.get('building_id') or data.get('flat_number'):
        flat_id = _resolve_flat_id(sb, data)
        if isinstance(flat_id, tuple):
            return flat_id
        data['flat_id'] = flat_id

    allowed = {k: v for k, v in data.items() if k in ('full_name', 'phone', 'role', 'flat_id', 'is_active')}
    if 'role' in allowed and allowed['role'] not in ('resident', 'tenant', 'committee_member'):
        return jsonify({'error': 'Invalid role'}), 400
    if not allowed:
        return jsonify({'error': 'Nothing to update'}), 400

    result = sb.table('user_profiles').update(allowed).eq('id', resident_id).execute()
    return jsonify(result.data[0] if result.data else {'updated': True})


@admin_bp.delete('/residents/<resident_id>')
@require_auth
@require_role('super_admin')
def delete_resident(resident_id):
    sb = get_admin_client()
    existing = sb.table('user_profiles').select('id').eq('id', resident_id).eq('society_id', g.society_id).maybe_single().execute()
    if not existing.data:
        return jsonify({'error': 'Resident not found'}), 404
    try:
        sb.table('family_members').delete().eq('flat_id',
            sb.table('user_profiles').select('flat_id').eq('id', resident_id).maybe_single().execute().data.get('flat_id', '')
        ).execute()
    except Exception:
        pass
    # --- Cascade-delete common dependent rows referencing this user ---
    try:
        sb.table('visitor_otps').delete().eq('created_by', resident_id).execute()
    except Exception:
        pass

    # Delete vehicle entry logs first (they reference vehicles), then vehicles
    try:
        v_res = sb.table('vehicles').select('id').eq('owner_id', resident_id).execute()
        v_ids = [v['id'] for v in (v_res.data or [])]
        if v_ids:
            sb.table('vehicle_entry_logs').delete().in_('vehicle_id', v_ids).execute()
    except Exception:
        pass

    try:
        sb.table('vehicles').delete().eq('owner_id', resident_id).execute()
    except Exception:
        pass

    try:
        sb.table('helper_flat_links').delete().eq('resident_id', resident_id).execute()
    except Exception:
        pass

    try:
        sb.table('helper_ratings').delete().eq('resident_id', resident_id).execute()
    except Exception:
        pass

    # Notices acknowledgments, event RSVPs and poll votes by this resident
    try:
        sb.table('notice_acknowledgments').delete().eq('resident_id', resident_id).execute()
    except Exception:
        pass

    try:
        sb.table('event_rsvp').delete().eq('resident_id', resident_id).execute()
    except Exception:
        pass

    try:
        sb.table('poll_votes').delete().eq('voter_id', resident_id).execute()
    except Exception:
        pass

    # Polls created by this resident (remove votes/options first)
    try:
        polls = sb.table('polls').select('id').eq('created_by', resident_id).execute().data or []
        poll_ids = [p['id'] for p in polls]
        if poll_ids:
            sb.table('poll_votes').delete().in_('poll_id', poll_ids).execute()
            sb.table('poll_options').delete().in_('poll_id', poll_ids).execute()
            sb.table('polls').delete().in_('id', poll_ids).execute()
    except Exception:
        pass

    # Events created by this resident (remove RSVPs first)
    try:
        events = sb.table('events').select('id').eq('created_by', resident_id).execute().data or []
        event_ids = [e['id'] for e in events]
        if event_ids:
            sb.table('event_rsvp').delete().in_('event_id', event_ids).execute()
            sb.table('events').delete().in_('id', event_ids).execute()
    except Exception:
        pass

    # Forum threads/replies
    try:
        threads = sb.table('forum_threads').select('id').eq('created_by', resident_id).execute().data or []
        thread_ids = [t['id'] for t in threads]
        if thread_ids:
            sb.table('forum_replies').delete().in_('thread_id', thread_ids).execute()
            sb.table('forum_threads').delete().in_('id', thread_ids).execute()
    except Exception:
        pass

    try:
        sb.table('forum_replies').delete().eq('posted_by', resident_id).execute()
    except Exception:
        pass

    # Personal and society documents uploaded by this user
    try:
        sb.table('personal_documents').delete().eq('uploaded_by', resident_id).execute()
    except Exception:
        pass
    try:
        sb.table('society_documents').delete().eq('uploaded_by', resident_id).execute()
    except Exception:
        pass

    # Helpdesk tickets and updates
    try:
        tickets = sb.table('helpdesk_tickets').select('id').eq('raised_by', resident_id).execute().data or []
        ticket_ids = [t['id'] for t in tickets]
        if ticket_ids:
            sb.table('ticket_updates').delete().in_('ticket_id', ticket_ids).execute()
            sb.table('helpdesk_tickets').delete().in_('id', ticket_ids).execute()
    except Exception:
        pass
    try:
        sb.table('ticket_updates').delete().eq('updated_by', resident_id).execute()
    except Exception:
        pass

    # Security alerts triggered by this resident
    try:
        sb.table('security_alerts').delete().eq('triggered_by', resident_id).execute()
    except Exception:
        pass

    # Notices posted by this resident
    try:
        sb.table('notices').delete().eq('posted_by', resident_id).execute()
    except Exception:
        pass

    # Expenses recorded by this resident
    try:
        sb.table('expenses').delete().eq('recorded_by', resident_id).execute()
    except Exception:
        pass

    # Visitor logs where this resident was the guard
    try:
        sb.table('visitor_logs').delete().eq('guard_id', resident_id).execute()
    except Exception:
        pass

    # Finally, remove the user profile itself
    sb.table('user_profiles').delete().eq('id', resident_id).execute()
    return jsonify({'deleted': True})


# ── Family members ────────────────────────────────────────────────────────────
@admin_bp.get('/residents/<resident_id>/family')
@require_auth
@require_role('super_admin', 'committee_member')
def list_family(resident_id):
    sb = get_admin_client()
    profile = sb.table('user_profiles').select('flat_id').eq('id', resident_id).eq('society_id', g.society_id).maybe_single().execute()
    if not profile.data or not profile.data.get('flat_id'):
        return jsonify([])
    return jsonify(sb.table('family_members').select('*').eq('flat_id', profile.data['flat_id']).eq('is_active', True).execute().data or [])


@admin_bp.post('/residents/<resident_id>/family')
@require_auth
@require_role('super_admin', 'committee_member')
def add_family_member(resident_id):
    data = request.get_json(silent=True) or {}
    if not data.get('full_name'):
        return jsonify({'error': 'full_name required'}), 400
    sb = get_admin_client()
    profile = sb.table('user_profiles').select('flat_id').eq('id', resident_id).eq('society_id', g.society_id).maybe_single().execute()
    if not profile.data or not profile.data.get('flat_id'):
        return jsonify({'error': 'Resident has no flat assigned'}), 400
    result = sb.table('family_members').insert({
        'flat_id':    profile.data['flat_id'],
        'society_id': g.society_id,
        'full_name':  data['full_name'],
        'relation':   data.get('relation'),
        'phone':      data.get('phone'),
    }).execute()
    return jsonify(result.data[0]), 201


@admin_bp.patch('/family/<member_id>')
@require_auth
@require_role('super_admin', 'committee_member')
def update_family_member(member_id):
    data = request.get_json(silent=True) or {}
    sb = get_admin_client()
    allowed = {k: v for k, v in data.items() if k in ('full_name', 'relation', 'phone', 'is_active')}
    if not allowed:
        return jsonify({'error': 'Nothing to update'}), 400
    result = sb.table('family_members').update(allowed).eq('id', member_id).eq('society_id', g.society_id).execute()
    return jsonify(result.data[0] if result.data else {'updated': True})


@admin_bp.delete('/family/<member_id>')
@require_auth
@require_role('super_admin', 'committee_member')
def delete_family_member(member_id):
    sb = get_admin_client()
    sb.table('family_members').update({'is_active': False}).eq('id', member_id).eq('society_id', g.society_id).execute()
    return jsonify({'deleted': True})

@admin_bp.post('/gates')
@require_auth
@require_role('super_admin', 'committee_member')
def create_gate():
    data = request.get_json(silent=True) or {}
    if not data.get('name'):
        return jsonify({'error': 'name required'}), 400
    sb = get_admin_client()
    result = sb.table('gates').insert({'society_id': g.society_id, 'name': data['name'], 'type': data.get('type', 'entry_exit')}).execute()
    return jsonify(result.data[0]), 201

@admin_bp.get('/gates')
@require_auth
def list_gates():
    sb = get_admin_client()
    return jsonify(sb.table('gates').select('*').eq('society_id', g.society_id).execute().data)

@admin_bp.delete('/gates/<gate_id>')
@require_auth
@require_role('super_admin', 'committee_member')
def delete_gate(gate_id):
    sb = get_admin_client()
    existing = sb.table('gates').select('id').eq('id', gate_id).eq('society_id', g.society_id).maybe_single().execute()
    if not existing.data:
        return jsonify({'error': 'Gate not found'}), 404
    sb.table('gates').delete().eq('id', gate_id).execute()
    return jsonify({'deleted': True})

@admin_bp.patch('/users/<user_id>/role')
@require_auth
@require_role('super_admin')
def change_user_role(user_id):
    role = (request.get_json(silent=True) or {}).get('role')
    valid_roles = ('super_admin', 'committee_member', 'resident', 'tenant', 'guard', 'facility_staff', 'vendor')
    if role not in valid_roles:
        return jsonify({'error': f'Invalid role. Must be one of {valid_roles}'}), 400
    sb = get_admin_client()
    sb.table('user_profiles').update({'role': role}).eq('id', user_id).execute()
    return jsonify({'role': role})


# ── Authorized Guards (Google Group Authentication Integration) ───────────────
@admin_bp.get('/authorized-guards')
@require_auth
@require_role('super_admin', 'committee_member')
def list_authorized_guards():
    sb = get_admin_client()
    try:
        res = sb.table('authorized_guards').select('*').order('created_at', desc=True).execute()
        return jsonify(res.data)
    except Exception as e:
        if 'authorized_guards' in str(e):
            return jsonify({
                'error': 'Database table authorized_guards is not configured.',
                'detail': 'Please run the SQL Table Setup in your Supabase SQL Editor first.'
            }), 500
        return jsonify({'error': str(e)}), 400

@admin_bp.post('/authorized-guards')
@require_auth
@require_role('super_admin', 'committee_member')
def add_authorized_guard():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    name = (data.get('name') or '').strip()
    gate_id = (data.get('gate_id') or '').strip()
    if not email:
        return jsonify({'error': 'email is required'}), 400
    sb = get_admin_client()
    try:
        result = sb.table('authorized_guards').insert({
            'email': email,
            'name': name,
            'gate_id': gate_id or None,
            'active': True
        }).execute()
        return jsonify(result.data[0]), 201
    except Exception as e:
        if 'authorized_guards' in str(e):
            return jsonify({
                'error': 'Database table authorized_guards is not configured.',
                'detail': 'Please run the SQL Table Setup in your Supabase SQL Editor first.'
            }), 500
        return jsonify({'error': str(e)}), 400

@admin_bp.patch('/authorized-guards/<guard_id>')
@require_auth
@require_role('super_admin', 'committee_member')
def update_authorized_guard(guard_id):
    data = request.get_json(silent=True) or {}
    allowed = ['active', 'name', 'gate_id']
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates and 'active' not in data:
        return jsonify({'error': 'No valid fields to update'}), 400
    sb = get_admin_client()
    try:
        result = sb.table('authorized_guards').update(updates).eq('id', guard_id).execute()
        return jsonify(result.data[0] if result.data else {})
    except Exception as e:
        if 'authorized_guards' in str(e):
            return jsonify({
                'error': 'Database table authorized_guards is not configured.',
                'detail': 'Please run the SQL Table Setup in your Supabase SQL Editor first.'
            }), 500
        return jsonify({'error': str(e)}), 400

@admin_bp.delete('/authorized-guards/<guard_id>')
@require_auth
@require_role('super_admin', 'committee_member')
def delete_authorized_guard(guard_id):
    sb = get_admin_client()
    try:
        sb.table('authorized_guards').delete().eq('id', guard_id).execute()
        return jsonify({'deleted': True})
    except Exception as e:
        if 'authorized_guards' in str(e):
            return jsonify({
                'error': 'Database table authorized_guards is not configured.',
                'detail': 'Please run the SQL Table Setup in your Supabase SQL Editor first.'
            }), 500
        return jsonify({'error': str(e)}), 400


# ── Google Group Settings & Sync Endpoints ────────────────────────────────────
@admin_bp.get('/google-group/config')
@require_auth
@require_role('super_admin', 'committee_member')
def get_google_group_config():
    from ..utils.google_groups import load_config
    cfg = load_config()
    return jsonify({
        'group_email': cfg.get('group_email', ''),
        'integration_mode': cfg.get('integration_mode', 'mock'),
        'has_service_account': bool(cfg.get('service_account_json'))
    })


@admin_bp.post('/google-group/config')
@require_auth
@require_role('super_admin', 'committee_member')
def save_google_group_config():
    data = request.get_json(silent=True) or {}
    group_email = (data.get('group_email') or '').strip().lower()
    integration_mode = data.get('integration_mode', 'mock')
    service_account_json = data.get('service_account_json', '')

    if not group_email:
        return jsonify({'error': 'Group email is required'}), 400
    if integration_mode not in ('mock', 'real'):
        return jsonify({'error': 'Invalid integration mode'}), 400

    from ..utils.google_groups import load_config, save_config
    cfg = load_config()
    cfg['group_email'] = group_email
    cfg['integration_mode'] = integration_mode
    if service_account_json.strip():
        cfg['service_account_json'] = service_account_json.strip()

    if save_config(cfg):
        return jsonify({'message': 'Configuration saved successfully'})
    return jsonify({'error': 'Failed to save configuration'}), 500


@admin_bp.post('/google-group/sync')
@require_auth
@require_role('super_admin', 'committee_member')
def sync_google_group():
    from ..utils.google_groups import sync_google_group_to_db
    from flask import current_app
    res = sync_google_group_to_db(current_app)
    if res.get('success'):
        return jsonify(res)
    return jsonify({'error': res.get('error', 'Sync failed')}), 500


@admin_bp.get('/google-group/mock-members')
@require_auth
@require_role('super_admin', 'committee_member')
def get_mock_members():
    from ..utils.google_groups import load_config
    cfg = load_config()
    return jsonify(cfg.get('mock_members', []))


@admin_bp.post('/google-group/mock-members')
@require_auth
@require_role('super_admin', 'committee_member')
def save_mock_members():
    data = request.get_json(silent=True)
    if not isinstance(data, list):
        return jsonify({'error': 'Data must be an array of members'}), 400

    # Validate members format
    validated = []
    for idx, item in enumerate(data):
        email = (item.get('email') or '').strip().lower()
        name = (item.get('name') or '').strip()
        gate_id = (item.get('gate_id') or 'GATE-A').strip()
        if not email:
            return jsonify({'error': f'Email is required for member at index {idx}'}), 400
        validated.append({
            'email': email,
            'name': name or 'Google Group Guard',
            'gate_id': gate_id or 'GATE-A'
        })

    from ..utils.google_groups import load_config, save_config
    cfg = load_config()
    cfg['mock_members'] = validated
    if save_config(cfg):
        return jsonify({'message': 'Mock members updated successfully', 'members': validated})
    return jsonify({'error': 'Failed to save mock members'}), 500
