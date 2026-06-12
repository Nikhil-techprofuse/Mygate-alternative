from flask import Blueprint, request, jsonify, g
from datetime import datetime, timezone
from ..supabase_client import get_admin_client
from ..utils.auth_middleware import require_auth, require_role, has_flat
from ..utils.otp import generate_numeric_otp

visitors_bp = Blueprint('visitors', __name__)


def cleanup_expired_visitor_otps(sb, flat_id=None):
    """Delete visitor OTP invites past their valid_until time."""
    now = datetime.now(timezone.utc).isoformat()
    query = sb.table('visitor_otps').delete().lt('valid_until', now)
    if flat_id:
        query = query.eq('flat_id', flat_id)
    result = query.execute()
    return len(result.data or [])


def verify_visitor_otp_internal(sb, society_id, guard_id, otp_code, gate_id=None):
    """Verify a visitor OTP and log entry. Returns dict with success, data/error, status."""
    now = datetime.now(timezone.utc).isoformat()

    otp_check = (
        sb.table('visitor_otps')
        .select('id, is_used, valid_from, valid_until, flat_id, flats(society_id)')
        .eq('otp_code', otp_code)
        .limit(1)
        .execute()
    )

    if not otp_check.data:
        return {'success': False, 'error': 'Unknown OTP code', 'status': 404, 'not_found': True}

    otp_info = otp_check.data[0]

    if otp_info.get('flats', {}).get('society_id') != society_id:
        return {'success': False, 'error': 'OTP belongs to a different society', 'status': 403}

    if otp_info.get('is_used'):
        return {'success': False, 'error': 'OTP already used', 'status': 400}

    if otp_info.get('valid_from') and otp_info['valid_from'] > now:
        return {'success': False, 'error': 'OTP not yet valid', 'status': 400}
    if otp_info.get('valid_until') and otp_info['valid_until'] < now:
        sb.table('visitor_otps').delete().eq('id', otp_info['id']).execute()
        return {'success': False, 'error': 'OTP expired', 'status': 400}

    otp_row = (
        sb.table('visitor_otps')
        .select('*, flats(flat_number, building_id)')
        .eq('id', otp_info['id'])
        .limit(1)
        .execute()
    )

    invite = otp_row.data[0]
    log_result = sb.table('visitor_logs').insert({
        'society_id':      society_id,
        'flat_id':         invite['flat_id'],
        'gate_id':         gate_id,
        'guard_id':        guard_id,
        'visitor_name':    invite['visitor_name'],
        'visitor_phone':   invite['visitor_phone'],
        'visitor_type':    'guest',
        'approval_status': 'pre_approved',
        'entry_time':      now,
    }).execute()

    if not invite.get('is_recurring'):
        sb.table('visitor_otps').update({'is_used': True}).eq('id', invite['id']).execute()

    return {
        'success': True,
        'data': {
            'status':       'approved',
            'visitor_name': invite['visitor_name'],
            'visitor_phone': invite.get('visitor_phone'),
            'valid_until':  invite.get('valid_until'),
            'flat':         invite.get('flats', {}),
            'log_id':       log_result.data[0]['id'],
        },
    }


# ── M2: Pre-approved OTP invite ───────────────────────────────────────────────

@visitors_bp.post('/invite')
@require_auth
@require_role('resident', 'tenant')
def create_invite():
    """Resident creates a pre-approved OTP invite for a guest."""
    data = request.get_json(silent=True) or {}
    required = ['visitor_name', 'valid_from', 'valid_until']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'error': f'Missing fields: {missing}'}), 400

    if not has_flat():
        return jsonify({'error': 'No flat assigned to your account. Contact admin.'}), 400

    otp_code = generate_numeric_otp(6)
    sb = get_admin_client()

    result = sb.table('visitor_otps').insert({
        'flat_id':       g.flat_id,
        'created_by':    g.user_id,
        'otp_code':      otp_code,
        'visitor_name':  data['visitor_name'],
        'visitor_phone': data.get('visitor_phone'),
        'valid_from':    data['valid_from'],    # Frontend sends UTC ISO string
        'valid_until':   data['valid_until'],   # Frontend sends UTC ISO string
        'is_recurring':  data.get('is_recurring', False),
    }).execute()

    return jsonify({'otp_code': otp_code, 'invite': result.data[0]}), 201


@visitors_bp.get('/invites')
@require_auth
@require_role('resident', 'tenant')
def list_invites():
    """List active OTP invites for the resident's flat (expired ones are auto-deleted)."""
    sb = get_admin_client()
    cleanup_expired_visitor_otps(sb, flat_id=g.flat_id)
    result = (
        sb.table('visitor_otps')
        .select('*')
        .eq('flat_id', g.flat_id)
        .order('created_at', desc=True)
        .execute()
    )
    return jsonify(result.data)


@visitors_bp.delete('/invites/<invite_id>')
@require_auth
@require_role('resident', 'tenant')
def cancel_invite(invite_id):
    """Resident cancels/deletes an OTP invite."""
    sb = get_admin_client()
    row = (
        sb.table('visitor_otps')
        .select('id, flat_id')
        .eq('id', invite_id)
        .limit(1)
        .execute()
    )
    if not row.data:
        return jsonify({'error': 'Invite not found'}), 404
    if row.data[0]['flat_id'] != g.flat_id:
        return jsonify({'error': 'Not your invite'}), 403
    sb.table('visitor_otps').delete().eq('id', invite_id).execute()
    return jsonify({'deleted': invite_id})


@visitors_bp.post('/verify-otp')
@require_auth
@require_role('guard')
def verify_visitor_otp():
    """Guard verifies a visitor OTP at the gate."""
    data = request.get_json(silent=True) or {}
    otp_code = (data.get('otp_code') or '').strip()
    gate_id  = data.get('gate_id')
    if not otp_code:
        return jsonify({'error': 'otp_code is required'}), 400

    sb = get_admin_client()
    result = verify_visitor_otp_internal(sb, g.society_id, g.user_id, otp_code, gate_id=gate_id)
    if result['success']:
        return jsonify(result['data'])
    return jsonify({'error': result['error']}), result['status']


# ── M2: Walk-in (unexpected) visitor ─────────────────────────────────────────

@visitors_bp.post('/walkin')
@require_auth
@require_role('guard')
def log_walkin():
    """Guard logs a walk-in visitor and fires realtime push to resident."""
    data = request.get_json(silent=True) or {}
    required = ['visitor_name', 'flat_id']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'error': f'Missing fields: {missing}'}), 400

    sb = get_admin_client()
    now = datetime.now(timezone.utc).isoformat()

    result = sb.table('visitor_logs').insert({
        'society_id':      g.society_id,
        'flat_id':         data['flat_id'],
        'gate_id':         data.get('gate_id') or g.profile.get('gate_id'),
        'guard_id':        g.user_id,
        'visitor_name':    data['visitor_name'],
        'visitor_phone':   data.get('visitor_phone'),
        'visitor_photo_url': data.get('visitor_photo_url'),
        'visitor_type':    data.get('visitor_type', 'guest'),
        'purpose':         data.get('purpose'),
        'approval_status': 'pending',
        'entry_time':      now,
    }).execute()

    log_id = result.data[0]['id']
    log = (
        sb.table('visitor_logs')
        .select('*, flats(flat_number, buildings(name))')
        .eq('id', log_id)
        .single()
        .execute()
    )
    return jsonify({'log_id': log_id, 'status': 'pending_approval', 'log': log.data}), 201


@visitors_bp.patch('/<log_id>/approve')
@require_auth
@require_role('resident', 'tenant')
def approve_visitor(log_id):
    """Resident approves or denies a walk-in visitor."""
    data = request.get_json(silent=True) or {}
    decision = data.get('decision')  # 'approved' | 'denied'
    if decision not in ('approved', 'denied'):
        return jsonify({'error': "decision must be 'approved' or 'denied'"}), 400

    sb = get_admin_client()
    # Verify this log belongs to the resident's flat
    log = (
        sb.table('visitor_logs')
        .select('flat_id, approval_status')
        .eq('id', log_id)
        .single()
        .execute()
    )
    if not log.data:
        return jsonify({'error': 'Visitor log not found'}), 404
    if log.data['flat_id'] != g.flat_id:
        return jsonify({'error': 'Not your flat'}), 403
    if log.data['approval_status'] != 'pending':
        return jsonify({'error': 'Already decided'}), 409

    sb.table('visitor_logs').update({'approval_status': decision}).eq('id', log_id).execute()
    return jsonify({'log_id': log_id, 'status': decision})


@visitors_bp.patch('/<log_id>/exit')
@require_auth
@require_role('guard')
def log_exit(log_id):
    """Guard logs visitor exit."""
    now = datetime.now(timezone.utc).isoformat()
    sb = get_admin_client()
    sb.table('visitor_logs').update({'exit_time': now}).eq('id', log_id).execute()
    return jsonify({'log_id': log_id, 'exit_time': now})


# ── Visitor History ───────────────────────────────────────────────────────────

@visitors_bp.get('/')
@require_auth
def list_visitors():
    """
    Guards: all logs for their gate today.
    Residents: their flat's visitor history.
    Admins: filterable by flat / gate / date.
    """
    sb   = get_admin_client()
    role = g.role
    params = request.args

    query = sb.table('visitor_logs').select('*, flats(flat_number)')

    if role == 'guard':
        today = datetime.now(timezone.utc).date().isoformat()
        query = query.gte('entry_time', today)
        if g.profile.get('gate_id'):
            query = query.eq('gate_id', g.profile['gate_id'])
    elif role in ('resident', 'tenant'):
        query = query.eq('flat_id', g.flat_id)
    else:
        # Admin — optional filters
        if params.get('flat_id'):
            query = query.eq('flat_id', params['flat_id'])
        if params.get('from'):
            query = query.gte('entry_time', params['from'])
        if params.get('to'):
            query = query.lte('entry_time', params['to'])
        if params.get('visitor_type'):
            query = query.eq('visitor_type', params['visitor_type'])
        query = query.eq('society_id', g.society_id)

    result = query.order('entry_time', desc=True).limit(200).execute()
    return jsonify(result.data)


# ── M1: Gate queue (live) ─────────────────────────────────────────────────────

@visitors_bp.get('/queue')
@require_auth
@require_role('guard')
def gate_queue():
    """Returns pending-approval visitors at guard's current gate."""
    sb  = get_admin_client()
    res = (
        sb.table('visitor_logs')
        .select('*, flats(flat_number, buildings(name))')
        .eq('society_id', g.society_id)
        .eq('approval_status', 'pending')
        .order('entry_time', desc=True)
        .execute()
    )
    return jsonify(res.data)
