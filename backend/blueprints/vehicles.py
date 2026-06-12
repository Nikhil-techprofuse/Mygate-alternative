from flask import Blueprint, request, jsonify, g
from datetime import datetime, timezone
from ..supabase_client import get_admin_client
from ..utils.auth_middleware import require_auth, require_role, has_flat

vehicles_bp = Blueprint('vehicles', __name__)


@vehicles_bp.get('/')
@require_auth
def list_vehicles():
    sb = get_admin_client()
    q = sb.table('vehicles').select('*, parking_slots(slot_name), flats(flat_number)')
    if g.role in ('resident', 'tenant'):
        q = q.eq('flat_id', g.flat_id)
    else:
        q = q.eq('society_id', g.society_id)
        if request.args.get('flat_id'):
            q = q.eq('flat_id', request.args['flat_id'])
    return jsonify(q.execute().data)


@vehicles_bp.post('/')
@require_auth
@require_role('resident', 'tenant', 'super_admin', 'committee_member')
def add_vehicle():
    data = request.get_json(silent=True) or {}
    required = ['number_plate', 'vehicle_type']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'error': f'Missing: {missing}'}), 400

    sb = get_admin_client()
    flat_id = g.flat_id if g.role in ('resident', 'tenant') else data.get('flat_id')

    if not flat_id or flat_id == '00000000-0000-0000-0000-000000000000':
        return jsonify({'error': 'No flat linked to this account. Ask admin to assign a flat first.'}), 400

    # Enforce flat vehicle limits
    flat  = sb.table('flats').select('max_cars, max_two_wheelers').eq('id', flat_id).single().execute()
    fdata = flat.data or {}
    vtype = data['vehicle_type']
    existing = sb.table('vehicles').select('id, vehicle_type').eq('flat_id', flat_id).eq('status', 'active').execute()
    cars  = sum(1 for v in (existing.data or []) if v['vehicle_type'] == 'car')
    bikes = sum(1 for v in (existing.data or []) if v['vehicle_type'] in ('bike', 'scooter'))
    if vtype == 'car' and cars >= (fdata.get('max_cars') or 999):
        return jsonify({'error': 'Car slot limit reached for this flat'}), 409
    if vtype in ('bike', 'scooter') and bikes >= (fdata.get('max_two_wheelers') or 999):
        return jsonify({'error': 'Two-wheeler slot limit reached for this flat'}), 409

    result = sb.table('vehicles').insert({
        'society_id':     g.society_id,
        'flat_id':        flat_id,
        'owner_id':       g.user_id,
        'number_plate':   data['number_plate'].upper().strip(),
        'vehicle_type':   vtype,
        'parking_slot_id': data.get('parking_slot_id'),
    }).execute()
    # Attach optional metadata as a note in status (schema has no make/model/color)
    return jsonify(result.data[0]), 201


@vehicles_bp.post('/lookup')
@require_auth
@require_role('guard', 'super_admin', 'committee_member')
def lookup_plate():
    """Guard looks up a number plate — returns owner info or flags as non-resident vehicle."""
    plate = (request.get_json(silent=True) or {}).get('number_plate', '').upper().strip()
    if not plate:
        return jsonify({'error': 'number_plate required'}), 400
    sb = get_admin_client()
    result = (
        sb.table('vehicles')
        .select('*, flats(flat_number), user_profiles(full_name, phone)')
        .eq('number_plate', plate)
        .eq('society_id', g.society_id)
        .limit(1)
        .execute()
    )
    if result.data and len(result.data) > 0:
        return jsonify({'found': True, 'vehicle': result.data[0]})
    return jsonify({'found': False, 'message': 'Non-resident vehicle — will be logged as visitor vehicle'})


@vehicles_bp.post('/entry')
@require_auth
@require_role('guard')
def log_entry():
    data = request.get_json(silent=True) or {}
    plate = (data.get('number_plate') or '').upper().strip()
    if not plate:
        return jsonify({'error': 'number_plate required'}), 400
    sb = get_admin_client()
    vehicle = (
        sb.table('vehicles').select('id').eq('number_plate', plate)
        .eq('society_id', g.society_id).limit(1).execute()
    )
    vehicle_id = vehicle.data[0]['id'] if (vehicle.data and len(vehicle.data) > 0) else None
    now = datetime.now(timezone.utc).isoformat()
    entry = sb.table('vehicle_entry_logs').insert({
        'society_id':        g.society_id,
        'gate_id':           data.get('gate_id'),
        'guard_id':          g.user_id,
        'vehicle_id':        vehicle_id,
        'number_plate':      plate,
        'is_visitor_vehicle': vehicle_id is None,
        'entry_time':        now,
    }).execute()
    return jsonify(entry.data[0]), 201


@vehicles_bp.patch('/entry/<entry_id>/exit')
@require_auth
@require_role('guard')
def log_vehicle_exit(entry_id):
    now = datetime.now(timezone.utc).isoformat()
    sb = get_admin_client()
    sb.table('vehicle_entry_logs').update({'exit_time': now}).eq('id', entry_id).execute()
    return jsonify({'exit_time': now})


@vehicles_bp.get('/entries')
@require_auth
def list_vehicle_entries():
    """Today's vehicle entry/exit log. Guard sees their gate; admin sees all."""
    sb = get_admin_client()
    today = datetime.now(timezone.utc).date().isoformat()
    q = (
        sb.table('vehicle_entry_logs')
        .select('*, vehicles(flat_id, flats(flat_number))')
        .eq('society_id', g.society_id)
        .gte('entry_time', today)
        .order('entry_time', desc=True)
    )
    if g.role == 'guard' and g.profile.get('gate_id'):
        q = q.eq('gate_id', g.profile['gate_id'])
    if request.args.get('date'):
        q = q.gte('entry_time', request.args['date'])
    return jsonify(q.limit(200).execute().data)


@vehicles_bp.patch('/<vehicle_id>')
@require_auth
@require_role('resident', 'tenant', 'super_admin', 'committee_member')
def update_vehicle(vehicle_id):
    """Update vehicle status (active/sold/transferred) or parking slot."""
    data = request.get_json(silent=True) or {}
    allowed = {'status', 'parking_slot_id'}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({'error': 'No valid fields to update'}), 400
    sb = get_admin_client()
    # Residents can only update their own vehicles
    q = sb.table('vehicles').update(updates).eq('id', vehicle_id)
    if g.role in ('resident', 'tenant'):
        q = q.eq('flat_id', g.flat_id)
    result = q.execute()
    if not result.data:
        return jsonify({'error': 'Vehicle not found or access denied'}), 404
    return jsonify(result.data[0])


@vehicles_bp.post('/dispute')
@require_auth
@require_role('guard', 'super_admin', 'committee_member')
def log_dispute():
    """Guard logs a parking dispute (unknown plate or spot conflict)."""
    data = request.get_json(silent=True) or {}
    plate = (data.get('number_plate') or '').upper().strip()
    if not plate:
        return jsonify({'error': 'number_plate required'}), 400
    sb = get_admin_client()
    result = sb.table('vehicle_disputes').insert({
        'society_id':  g.society_id,
        'gate_id':     g.profile.get('gate_id'),
        'guard_id':    g.user_id,
        'number_plate': plate,
        'description': data.get('note', ''),
    }).execute()
    return jsonify(result.data[0]), 201


@vehicles_bp.get('/parking-slots')
@require_auth
def list_parking_slots():
    sb = get_admin_client()
    q = sb.table('parking_slots').select('*, flats(flat_number)').eq('society_id', g.society_id)
    if request.args.get('building_id'):
        q = q.eq('building_id', request.args['building_id'])
    return jsonify(q.execute().data)


@vehicles_bp.post('/parking-slots')
@require_auth
@require_role('super_admin', 'committee_member')
def create_parking_slot():
    data = request.get_json(silent=True) or {}
    if not data.get('slot_name'):
        return jsonify({'error': 'slot_name required'}), 400
    sb = get_admin_client()
    result = sb.table('parking_slots').insert({
        'society_id':       g.society_id,
        'building_id':      data.get('building_id'),
        'slot_name':        data['slot_name'],
        'type':             data.get('type', 'open'),
        'flat_id':          data.get('flat_id'),
        'is_visitor_parking': data.get('is_visitor_parking', False),
    }).execute()
    return jsonify(result.data[0]), 201
