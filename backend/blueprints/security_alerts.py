from flask import Blueprint, request, jsonify, g
from datetime import datetime, timezone
from ..supabase_client import get_admin_client
from ..utils.auth_middleware import require_auth, require_role

security_alerts_bp = Blueprint('security_alerts', __name__)


@security_alerts_bp.post('/sos')
@require_auth
@require_role('resident', 'tenant')
def trigger_sos():
    """Resident panic button — logs alert; guard notified via Supabase Realtime."""
    sb  = get_admin_client()
    now = datetime.now(timezone.utc).isoformat()
    result = sb.table('security_alerts').insert({
        'society_id':   g.society_id,
        'flat_id':      g.flat_id,
        'triggered_by': g.user_id,
        'alert_type':   'sos',
        'alert_status': 'sent',
    }).execute()
    # Emergency contacts IVR/SMS handled by frontend calling /api/notifications/sos
    return jsonify({'alert': result.data[0]}), 201


@security_alerts_bp.patch('/<alert_id>/acknowledge')
@require_auth
@require_role('guard')
def acknowledge_alert(alert_id):
    now = datetime.now(timezone.utc).isoformat()
    sb  = get_admin_client()
    sb.table('security_alerts').update({
        'alert_status':          'acknowledged',
        'guard_acknowledged_by': g.user_id,
        'acknowledged_at':       now,
    }).eq('id', alert_id).execute()
    return jsonify({'status': 'acknowledged'})


@security_alerts_bp.patch('/<alert_id>/resolve')
@require_auth
@require_role('guard', 'super_admin', 'committee_member')
def resolve_alert(alert_id):
    data = request.get_json(silent=True) or {}
    now  = datetime.now(timezone.utc).isoformat()
    sb   = get_admin_client()
    sb.table('security_alerts').update({
        'alert_status':    'resolved',
        'resolved_at':     now,
        'resolution_note': data.get('note'),
    }).eq('id', alert_id).execute()
    return jsonify({'status': 'resolved'})


@security_alerts_bp.post('/broadcast')
@require_auth
@require_role('super_admin', 'committee_member')
def broadcast():
    data = request.get_json(silent=True) or {}
    if not data.get('title') or not data.get('message'):
        return jsonify({'error': 'title and message required'}), 400
    sb = get_admin_client()
    result = sb.table('admin_broadcasts').insert({
        'society_id':    g.society_id,
        'sent_by':       g.user_id,
        'title':         data['title'],
        'message':       data['message'],
        'broadcast_type': data.get('broadcast_type', 'both'),
    }).execute()
    return jsonify(result.data[0]), 201


@security_alerts_bp.get('/broadcasts')
@require_auth
def list_broadcasts():
    sb = get_admin_client()
    result = sb.table('admin_broadcasts').select('*').eq('society_id', g.society_id).order('sent_at', desc=True).execute()
    return jsonify(result.data)


@security_alerts_bp.get('/')
@require_auth
def list_alerts():
    sb = get_admin_client()
    q  = sb.table('security_alerts').select(
        '*, user_profiles!security_alerts_triggered_by_fkey(full_name), flats(flat_number)'
    ).eq('society_id', g.society_id)
    if request.args.get('status'):
        q = q.eq('alert_status', request.args['status'])
    if request.args.get('flat_id'):
        q = q.eq('flat_id', request.args['flat_id'])
    return jsonify(q.order('created_at', desc=True).limit(100).execute().data)


@security_alerts_bp.post('/emergency-contacts')
@require_auth
@require_role('resident', 'tenant')
def add_emergency_contact():
    data = request.get_json(silent=True) or {}
    if not data.get('name') or not data.get('phone'):
        return jsonify({'error': 'name and phone required'}), 400
    sb = get_admin_client()
    # Max 3 contacts
    existing = sb.table('emergency_contacts').select('id').eq('resident_id', g.user_id).execute()
    if len(existing.data or []) >= 3:
        return jsonify({'error': 'Maximum 3 emergency contacts allowed'}), 409
    result = sb.table('emergency_contacts').insert({
        'resident_id': g.user_id,
        'name':        data['name'],
        'phone':       data['phone'],
    }).execute()
    return jsonify(result.data[0]), 201


@security_alerts_bp.get('/emergency-contacts')
@require_auth
@require_role('resident', 'tenant')
def get_emergency_contacts():
    sb = get_admin_client()
    return jsonify(sb.table('emergency_contacts').select('*').eq('resident_id', g.user_id).execute().data)


@security_alerts_bp.delete('/emergency-contacts/<contact_id>')
@require_auth
@require_role('resident', 'tenant')
def delete_emergency_contact(contact_id):
    sb = get_admin_client()
    sb.table('emergency_contacts').delete().eq('id', contact_id).eq('resident_id', g.user_id).execute()
    return jsonify({'deleted': True})
