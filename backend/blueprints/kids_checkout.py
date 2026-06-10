from flask import Blueprint, request, jsonify, g
from datetime import datetime, timezone
from ..supabase_client import get_admin_client
from ..utils.auth_middleware import require_auth, require_role

kids_checkout_bp = Blueprint('kids_checkout', __name__)


@kids_checkout_bp.post('/toggle')
@require_auth
@require_role('resident', 'tenant')
def toggle_kids_checkout():
    enabled = (request.get_json(silent=True) or {}).get('enabled', False)
    sb = get_admin_client()
    sb.table('flats').update({'kids_checkout_enabled': bool(enabled)}).eq('id', g.flat_id).execute()
    return jsonify({'kids_checkout_enabled': bool(enabled)})


@kids_checkout_bp.post('/trusted-escort')
@require_auth
@require_role('resident', 'tenant')
def set_trusted_escorts():
    """escorts: [{name, phone_or_passcode}]"""
    escorts = (request.get_json(silent=True) or {}).get('escorts', [])
    sb = get_admin_client()
    sb.table('flats').update({'trusted_escorts': escorts}).eq('id', g.flat_id).execute()
    return jsonify({'trusted_escorts': escorts})


@kids_checkout_bp.post('/request')
@require_auth
@require_role('guard')
def request_checkout():
    """Guard initiates a kids checkout for a flat."""
    data    = request.get_json(silent=True) or {}
    flat_id = data.get('flat_id')
    if not flat_id:
        return jsonify({'error': 'flat_id required'}), 400
    sb  = get_admin_client()
    flat = sb.table('flats').select('kids_checkout_enabled').eq('id', flat_id).single().execute()
    if not flat.data or not flat.data.get('kids_checkout_enabled'):
        return jsonify({'error': 'Kids checkout not enabled for this flat'}), 422
    now = datetime.now(timezone.utc).isoformat()
    result = sb.table('kids_checkout_events').insert({
        'society_id': g.society_id,
        'flat_id':    flat_id,
        'gate_id':    data.get('gate_id'),
        'guard_id':   g.user_id,
        'event_type': 'unplanned',
        'status':     'pending',
    }).execute()
    return jsonify(result.data[0]), 201


@kids_checkout_bp.patch('/<event_id>/decide')
@require_auth
@require_role('resident', 'tenant')
def decide_checkout(event_id):
    decision = (request.get_json(silent=True) or {}).get('decision')
    if decision not in ('approved', 'denied'):
        return jsonify({'error': "decision must be 'approved' or 'denied'"}), 400
    sb  = get_admin_client()
    now = datetime.now(timezone.utc).isoformat()
    sb.table('kids_checkout_events').update({
        'status':      decision,
        'resolved_at': now,
    }).eq('id', event_id).eq('flat_id', g.flat_id).execute()
    return jsonify({'event_id': event_id, 'status': decision})


@kids_checkout_bp.post('/planned')
@require_auth
@require_role('resident', 'tenant')
def create_planned_exit():
    data = request.get_json(silent=True) or {}
    if not data.get('time_window_start') or not data.get('time_window_end'):
        return jsonify({'error': 'time_window_start and time_window_end required'}), 400
    sb = get_admin_client()
    result = sb.table('kids_checkout_events').insert({
        'society_id':       g.society_id,
        'flat_id':          g.flat_id,
        'event_type':       'planned',
        'status':           'approved',
        'escort_name':      data.get('escort_name'),
        'time_window_start': data['time_window_start'],
        'time_window_end':   data['time_window_end'],
    }).execute()
    return jsonify(result.data[0]), 201


@kids_checkout_bp.get('/')
@require_auth
def list_events():
    sb = get_admin_client()
    q  = sb.table('kids_checkout_events').select('*')
    if g.role in ('resident', 'tenant'):
        q = q.eq('flat_id', g.flat_id)
    else:
        q = q.eq('society_id', g.society_id)
    return jsonify(q.order('created_at', desc=True).execute().data)
