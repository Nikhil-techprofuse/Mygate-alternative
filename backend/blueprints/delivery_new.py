from flask import Blueprint, request, jsonify, g
from datetime import datetime, timezone
from ..supabase_client import get_admin_client
from ..utils.auth_middleware import require_auth, require_role
from ..utils.otp import generate_numeric_otp

delivery_bp = Blueprint('delivery', __name__)


@delivery_bp.post('/')
@require_auth
@require_role('guard')
def log_delivery():
    """Guard logs an incoming delivery."""
    data = request.get_json(silent=True) or {}
    if not data.get('flat_id'):
        return jsonify({'error': 'flat_id required'}), 400

    sb  = get_admin_client()
    now = datetime.now(timezone.utc).isoformat()

    # Check resident's leave_at_gate preference
    flat = sb.table('flats').select('id').eq('id', data['flat_id']).maybe_single().execute()
    if not flat.data:
        return jsonify({'error': 'Flat not found'}), 404

    leave_at_gate = data.get('leave_at_gate', False)
    parcel_otp    = generate_numeric_otp(6) if leave_at_gate else None

    result = sb.table('deliveries').insert({
        'society_id':       g.society_id,
        'flat_id':          data['flat_id'],
        'gate_id':          data.get('gate_id'),
        'guard_id':         g.user_id,
        'platform_id':      data.get('platform_id'),
        'tracking_id':      data.get('tracking_id'),
        'package_photo_url': data.get('package_photo_url'),
        'delivery_type':    data.get('delivery_type', 'standard'),
        'leave_at_gate':    leave_at_gate,
        'parcel_otp':       parcel_otp,
        'status':           'arrived',
        'entry_time':       now,
    }).execute()

    return jsonify({
        'delivery': result.data[0],
        'parcel_otp': parcel_otp,  # shown to guard for left-at-gate flows
    }), 201


@delivery_bp.patch('/<delivery_id>/allow')
@require_auth
@require_role('resident', 'tenant')
def allow_entry(delivery_id):
    """Resident approves delivery entry."""
    sb = get_admin_client()
    d = sb.table('deliveries').select('flat_id').eq('id', delivery_id).single().execute()
    if not d.data or d.data['flat_id'] != g.flat_id:
        return jsonify({'error': 'Not found or not your delivery'}), 403
    sb.table('deliveries').update({'status': 'allowed_in'}).eq('id', delivery_id).execute()
    return jsonify({'status': 'allowed_in'})


@delivery_bp.patch('/<delivery_id>/exit')
@require_auth
@require_role('guard')
def log_delivery_exit(delivery_id):
    now = datetime.now(timezone.utc).isoformat()
    sb  = get_admin_client()
    sb.table('deliveries').update({'exit_time': now, 'status': 'left_at_gate'}).eq('id', delivery_id).execute()
    return jsonify({'exit_time': now})


@delivery_bp.post('/<delivery_id>/collect')
@require_auth
@require_role('guard')
def collect_parcel(delivery_id):
    """Guard verifies OTP and marks parcel as collected."""
    otp = (request.get_json(silent=True) or {}).get('otp', '').strip()
    if not otp:
        return jsonify({'error': 'otp required'}), 400
    sb  = get_admin_client()
    
    # Check if delivery_id is a UUID or a tracking_id
    import uuid
    is_uuid = False
    try:
        uuid.UUID(delivery_id)
        is_uuid = True
    except ValueError:
        pass

    if is_uuid:
        d = sb.table('deliveries').select('id, parcel_otp, parcel_otp_used').eq('id', delivery_id).maybe_single().execute()
        d_data = d.data
    else:
        # Search by tracking ID
        d = (
            sb.table('deliveries')
            .select('id, parcel_otp, parcel_otp_used')
            .eq('tracking_id', delivery_id)
            .neq('status', 'collected')
            .order('entry_time', desc=True)
            .execute()
        )
        d_data = d.data[0] if d.data else None

    if not d_data:
        return jsonify({'error': 'Delivery not found'}), 404
    if d_data.get('parcel_otp_used'):
        return jsonify({'error': 'OTP already used'}), 409
    db_otp = str(d_data.get('parcel_otp') or '').strip()
    input_otp = str(otp).strip()
    if db_otp != input_otp:
        return jsonify({'error': 'Invalid OTP'}), 401
    now = datetime.now(timezone.utc).isoformat()
    sb.table('deliveries').update({
        'parcel_otp_used': True,
        'collected_at':    now,
        'status':          'collected',
    }).eq('id', d_data['id']).execute()
    return jsonify({'status': 'collected', 'collected_at': now})


@delivery_bp.get('/')
@require_auth
def list_deliveries():
    sb = get_admin_client()
    q  = sb.table('deliveries').select('*, flats(flat_number), delivery_platforms(name)')
    if g.role in ('resident', 'tenant'):
        q = q.eq('flat_id', g.flat_id)
    else:
        q = q.eq('society_id', g.society_id)
        if request.args.get('status'):
            q = q.eq('status', request.args['status'])
    return jsonify(q.order('entry_time', desc=True).limit(200).execute().data)


@delivery_bp.get('/platforms')
@require_auth
def list_platforms():
    sb = get_admin_client()
    return jsonify(
        sb.table('delivery_platforms').select('*').eq('society_id', g.society_id).execute().data
    )


@delivery_bp.post('/platforms')
@require_auth
@require_role('super_admin', 'committee_member')
def add_platform():
    data = request.get_json(silent=True) or {}
    if not data.get('name'):
        return jsonify({'error': 'name required'}), 400
    sb = get_admin_client()
    result = sb.table('delivery_platforms').insert({
        'society_id':          g.society_id,
        'name':                data['name'],
        'logo_url':            data.get('logo_url'),
        'allowed_hours_start': data.get('allowed_hours_start', '06:00'),
        'allowed_hours_end':   data.get('allowed_hours_end', '22:00'),
    }).execute()
    return jsonify(result.data[0]), 201
