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
                flat_number = f"{floor}{unit:02d}"   # e.g. floor 1, unit 3 → "103"
                flat_rows.append({
                    'society_id':  g.society_id,
                    'building_id': building_id,
                    'flat_number': flat_number,
                    'floor':       floor,
                })
        # Insert in batches of 50 to avoid request-size limits
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
    # Unlink residents from flats in this building before deletion
    flats = sb.table('flats').select('id').eq('building_id', building_id).execute().data or []
    flat_ids = [f['id'] for f in flats]
    if flat_ids:
        for fid in flat_ids:
            sb.table('user_profiles').update({'flat_id': None}).eq('flat_id', fid).execute()
        sb.table('family_members').delete().in_('flat_id', flat_ids).execute()
    # Delete flats (may fail if other FKs exist — handle gracefully)
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

    # Attach family members counts
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
    """Create a resident profile. Accepts building_id + floor + flat_number and
    finds or creates the flat automatically."""
    data = request.get_json(silent=True) or {}
    if not data.get('full_name'):
        return jsonify({'error': 'full_name is required'}), 400

    sb = get_admin_client()
    flat_id = _resolve_flat_id(sb, data)
    if isinstance(flat_id, tuple):   # error tuple
        return flat_id

    role = data.get('role', 'resident')
    if role not in ('resident', 'tenant', 'committee_member'):
        return jsonify({'error': 'Invalid role'}), 400

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
    """Given request data with either flat_id OR (building_id + floor + flat_number),
    return the flat UUID (creating the flat if it doesn't exist yet).
    Returns an error response tuple on failure."""
    import re as _re

    # Direct flat_id takes priority (used by internal calls)
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

    # Validate building belongs to this society
    bldg = sb.table('buildings').select('id, floors').eq('id', building_id).eq('society_id', g.society_id).limit(1).execute()
    if not bldg.data:
        return jsonify({'error': 'Building not found in this society'}), 404

    # Try to find existing flat
    q = sb.table('flats').select('id').eq('building_id', building_id).eq('flat_number', flat_number).limit(1).execute()
    if q.data:
        return q.data[0]['id']

    # Create the flat
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

    # Resolve flat from building/floor/flatno if provided
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
    existing = sb.table('user_profiles').select('id, flat_id').eq('id', resident_id).eq('society_id', g.society_id).limit(1).execute()
    if not existing.data:
        return jsonify({'error': 'Resident not found'}), 404

    flat_id = existing.data[0].get('flat_id')

    # Delete or null-out all FK references before deleting the profile row.
    # For content created by this user, delete it entirely:
    _delete_refs = [
        ('notices',          'posted_by'),
        ('polls',            'created_by'),
        ('events',           'created_by'),
        ('forum_posts',      'posted_by'),
        ('forum_comments',   'posted_by'),
        ('ticket_updates',   'updated_by'),
        ('security_alerts',  'triggered_by'),
        ('visitor_otps',     'created_by'),
    ]
    for table, col in _delete_refs:
        try:
            sb.table(table).delete().eq(col, resident_id).execute()
        except Exception:
            pass

    # For assigned references, null them out:
    try:
        sb.table('helpdesk_tickets').update({'raised_by': None}).eq('raised_by', resident_id).execute()
    except Exception:
        pass
    try:
        sb.table('helpdesk_tickets').update({'assigned_to': None}).eq('assigned_to', resident_id).execute()
    except Exception:
        pass

    # Delete family members linked to this flat
    if flat_id:
        try:
            sb.table('family_members').delete().eq('flat_id', flat_id).execute()
        except Exception:
            pass

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
