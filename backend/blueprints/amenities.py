from flask import Blueprint, request, jsonify, g
from ..supabase_client import get_admin_client
from ..utils.auth_middleware import require_auth, require_role

amenities_bp = Blueprint('amenities', __name__)

@amenities_bp.get('/')
@require_auth
def list_amenities():
    sb = get_admin_client()
    return jsonify(sb.table('amenities').select('*, amenity_slots(*)').eq('society_id', g.society_id).eq('is_active', True).execute().data)

@amenities_bp.post('/')
@require_auth
@require_role('super_admin', 'committee_member')
def create_amenity():
    data = request.get_json(silent=True) or {}
    if not data.get('name'):
        return jsonify({'error': 'name required'}), 400
    sb = get_admin_client()
    result = sb.table('amenities').insert({
        'society_id': g.society_id, 'name': data['name'],
        'description': data.get('description'), 'capacity': data.get('capacity'),
        'charge_per_slot': data.get('charge_per_slot', 0),
        'cooldown_minutes': data.get('cooldown_minutes', 0),
        'advance_booking_days': data.get('advance_booking_days', 7),
    }).execute()
    return jsonify(result.data[0]), 201

@amenities_bp.get('/<amenity_id>/bookings')
@require_auth
def amenity_bookings(amenity_id):
    sb = get_admin_client()
    q = sb.table('bookings').select('*, flats(flat_number)').eq('amenity_id', amenity_id)
    if request.args.get('date'):
        q = q.eq('booking_date', request.args['date'])
    return jsonify(q.execute().data)

@amenities_bp.post('/book')
@require_auth
@require_role('resident', 'tenant')
def book_amenity():
    data = request.get_json(silent=True) or {}
    required = ['amenity_id', 'booking_date', 'start_time', 'end_time']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'error': f'Missing: {missing}'}), 400
    sb = get_admin_client()
    # Check availability (no overlapping confirmed booking)
    overlap = (
        sb.table('bookings')
        .select('id')
        .eq('amenity_id', data['amenity_id'])
        .eq('booking_date', data['booking_date'])
        .eq('status', 'confirmed')
        .lte('start_time', data['end_time'])
        .gte('end_time', data['start_time'])
        .execute()
    )
    if overlap.data:
        return jsonify({'error': 'Slot already booked'}), 409
    amenity = sb.table('amenities').select('charge_per_slot').eq('id', data['amenity_id']).single().execute()
    result = sb.table('bookings').insert({
        'amenity_id': data['amenity_id'], 'flat_id': g.flat_id, 'booked_by': g.user_id,
        'booking_date': data['booking_date'], 'start_time': data['start_time'],
        'end_time': data['end_time'],
        'total_amount': amenity.data.get('charge_per_slot', 0) if amenity.data else 0,
        'status': 'pending_payment',
    }).execute()
    return jsonify(result.data[0]), 201

@amenities_bp.patch('/book/<booking_id>/confirm')
@require_auth
@require_role('super_admin', 'committee_member')
def confirm_booking(booking_id):
    sb = get_admin_client()
    sb.table('bookings').update({'status': 'confirmed'}).eq('id', booking_id).execute()
    return jsonify({'status': 'confirmed'})

@amenities_bp.patch('/book/<booking_id>/cancel')
@require_auth
def cancel_booking(booking_id):
    sb = get_admin_client()
    q = sb.table('bookings').select('flat_id').eq('id', booking_id).single().execute()
    if not q.data:
        return jsonify({'error': 'Not found'}), 404
    if g.role in ('resident', 'tenant') and q.data['flat_id'] != g.flat_id:
        return jsonify({'error': 'Forbidden'}), 403
    sb.table('bookings').update({'status': 'cancelled'}).eq('id', booking_id).execute()
    return jsonify({'status': 'cancelled'})

@amenities_bp.get('/my-bookings')
@require_auth
@require_role('resident', 'tenant')
def my_bookings():
    sb = get_admin_client()
    return jsonify(sb.table('bookings').select('*, amenities(name)').eq('flat_id', g.flat_id).order('booking_date', desc=True).execute().data)
