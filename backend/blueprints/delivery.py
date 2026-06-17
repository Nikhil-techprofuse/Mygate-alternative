from flask import Blueprint, request, jsonify, g
from datetime import datetime, timezone
from ..supabase_client import get_admin_client
from ..utils.auth_middleware import require_auth, require_role

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

    # Handle platform - can be ID or name
    platform_id = data.get('platform_id')
    platform_name = data.get('platform_name', '').strip()
    
    # If platform_name is provided, try to find or create platform
    if platform_name and not platform_id:
        # Try to find existing platform by name
        existing = sb.table('delivery_platforms').select('id').eq('society_id', g.society_id).ilike('name', platform_name).limit(1).execute()
        if existing.data:
            platform_id = existing.data[0]['id']
        else:
            # Create new platform entry
            new_platform = sb.table('delivery_platforms').insert({
                'society_id': g.society_id,
                'name': platform_name,
            }).execute()
            platform_id = new_platform.data[0]['id'] if new_platform.data else None

    result = sb.table('deliveries').insert({
        'society_id':       g.society_id,
        'flat_id':          data['flat_id'],
        'gate_id':          data.get('gate_id'),
        'guard_id':         g.user_id,
        'platform_id':      platform_id,
        'tracking_id':      data.get('tracking_id'),
        'package_photo_url': data.get('package_photo_url'),
        'delivery_type':    data.get('delivery_type', 'standard'),
        'status':           'arrived',
        'entry_time':       now,
    }).execute()

    return jsonify({'delivery': result.data[0]}), 201


@delivery_bp.patch('/<delivery_id>/decide')
@require_auth
@require_role('resident', 'tenant')
def resident_decision(delivery_id):
    """Resident makes decision: accept, reject, or leave_at_gate."""
    data = request.get_json(silent=True) or {}
    decision = data.get('decision')  # 'accept', 'reject', 'leave_at_gate'
    
    if decision not in ('accept', 'reject', 'leave_at_gate'):
        return jsonify({'error': "decision must be 'accept', 'reject', or 'leave_at_gate'"}), 400
    
    sb = get_admin_client()
    d = sb.table('deliveries').select('flat_id, status').eq('id', delivery_id).single().execute()
    if not d.data or d.data['flat_id'] != g.flat_id:
        return jsonify({'error': 'Not found or not your delivery'}), 403
    
    if d.data['status'] != 'arrived':
        return jsonify({'error': 'Delivery already processed'}), 409
    
    updates = {}
    parcel_otp = None
    
    if decision == 'accept':
        updates['status'] = 'allowed_in'
    elif decision == 'reject':
        updates['status'] = 'rejected'
        updates['exit_time'] = datetime.now(timezone.utc).isoformat()
    elif decision == 'leave_at_gate':
        parcel_otp = (data.get('otp') or '').strip() or None
        updates['status'] = 'left_at_gate'
        updates['leave_at_gate'] = True
        updates['parcel_otp'] = parcel_otp
        updates['exit_time'] = datetime.now(timezone.utc).isoformat()
    
    sb.table('deliveries').update(updates).eq('id', delivery_id).execute()
    
    response = {'status': updates['status']}
    if parcel_otp:
        response['parcel_otp'] = parcel_otp
    
    return jsonify(response)


@delivery_bp.patch('/<delivery_id>/allow')
@require_auth
@require_role('resident', 'tenant')
def allow_entry(delivery_id):
    """Resident approves delivery entry (legacy endpoint)."""
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


@delivery_bp.post('/<delivery_id>/mark-collected')
@require_auth
@require_role('guard')
def mark_collected(delivery_id):
    """Guard marks a left-at-gate delivery as collected/picked up."""
    sb = get_admin_client()
    d = sb.table('deliveries').select('id, status').eq('id', delivery_id).eq('society_id', g.society_id).maybe_single().execute()
    if not d.data:
        return jsonify({'error': 'Delivery not found'}), 404
    
    now = datetime.now(timezone.utc).isoformat()
    sb.table('deliveries').update({
        'status': 'collected',
        'collected_at': now,
        'parcel_otp_used': True,
    }).eq('id', delivery_id).execute()
    
    return jsonify({'status': 'collected', 'collected_at': now})


@delivery_bp.patch('/<delivery_id>/status')
@require_auth
@require_role('guard')
def update_delivery_status(delivery_id):
    """Guard updates the status of a delivery (e.g. arrived, left_at_gate, collected)."""
    data = request.get_json(silent=True) or {}
    new_status = data.get('status')
    if new_status not in ('arrived', 'left_at_gate', 'collected'):
        return jsonify({'error': "Invalid status. Must be 'arrived', 'left_at_gate', or 'collected'"}), 400

    sb = get_admin_client()
    d = sb.table('deliveries').select('id, status').eq('id', delivery_id).eq('society_id', g.society_id).maybe_single().execute()
    if not d.data:
        return jsonify({'error': 'Delivery not found'}), 404

    now = datetime.now(timezone.utc).isoformat()
    updates = {'status': new_status}
    if new_status == 'collected':
        updates['collected_at'] = now
        updates['parcel_otp_used'] = True
    elif new_status == 'left_at_gate':
        updates['exit_time'] = now
        updates['leave_at_gate'] = True
        updates['collected_at'] = None
        updates['parcel_otp_used'] = False
    elif new_status == 'arrived':
        updates['exit_time'] = None
        updates['leave_at_gate'] = False
        updates['collected_at'] = None
        updates['parcel_otp_used'] = False

    sb.table('deliveries').update(updates).eq('id', delivery_id).execute()
    return jsonify({'status': new_status})


@delivery_bp.get('/')
@require_auth
def list_deliveries():
    sb = get_admin_client()
    q  = sb.table('deliveries').select('id, society_id, flat_id, gate_id, guard_id, platform_id, tracking_id, package_photo_url, delivery_type, status, entry_time, exit_time, collected_at, leave_at_gate, parcel_otp, parcel_otp_used, flats(flat_number), delivery_platforms(name)')
    if g.role in ('resident', 'tenant'):
        q = q.eq('flat_id', g.flat_id)
    else:
        q = q.eq('society_id', g.society_id)
        if request.args.get('status'):
            status_list = request.args['status'].split(',')
            if len(status_list) > 1:
                q = q.in_('status', status_list)
            else:
                q = q.eq('status', status_list[0])
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
