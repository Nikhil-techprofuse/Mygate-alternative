from flask import Blueprint, request, jsonify, g
from datetime import datetime, timezone
from ..supabase_client import get_admin_client
from ..utils.auth_middleware import require_auth, require_role

helpdesk_bp = Blueprint('helpdesk', __name__)

@helpdesk_bp.post('/')
@require_auth
@require_role('resident', 'tenant')
def create_ticket():
    data = request.get_json(silent=True) or {}
    if not data.get('title') or not data.get('category'):
        return jsonify({'error': 'title and category required'}), 400
    sb = get_admin_client()
    result = sb.table('helpdesk_tickets').insert({
        'society_id': g.society_id, 'flat_id': g.flat_id, 'raised_by': g.user_id,
        'category': data['category'], 'title': data['title'],
        'description': data.get('description'), 'priority': data.get('priority', 'medium'),
    }).execute()
    return jsonify(result.data[0]), 201

@helpdesk_bp.get('/')
@require_auth
def list_tickets():
    sb = get_admin_client()
    q = sb.table('helpdesk_tickets').select('*, flats(flat_number), user_profiles(full_name)')
    if g.role in ('resident', 'tenant'):
        q = q.eq('flat_id', g.flat_id)
    else:
        q = q.eq('society_id', g.society_id)
        if request.args.get('status'):
            q = q.eq('status', request.args['status'])
        if request.args.get('category'):
            q = q.eq('category', request.args['category'])
    return jsonify(q.order('created_at', desc=True).execute().data)

@helpdesk_bp.patch('/<ticket_id>')
@require_auth
@require_role('super_admin', 'committee_member', 'facility_staff')
def update_ticket(ticket_id):
    data = request.get_json(silent=True) or {}
    allowed = ['status', 'assigned_to', 'sla_hours']
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({'error': 'No valid fields'}), 400
    sb = get_admin_client()
    if updates.get('status') == 'resolved':
        updates['resolved_at'] = datetime.now(timezone.utc).isoformat()
    sb.table('helpdesk_tickets').update(updates).eq('id', ticket_id).execute()
    if data.get('note'):
        sb.table('ticket_updates').insert({'ticket_id': ticket_id, 'updated_by': g.user_id, 'note': data['note'], 'status_changed_to': data.get('status')}).execute()
    return jsonify({'updated': True})

@helpdesk_bp.post('/<ticket_id>/rate')
@require_auth
@require_role('resident', 'tenant')
def rate_ticket(ticket_id):
    data = request.get_json(silent=True) or {}
    rating = data.get('rating')
    if not rating or not (1 <= int(rating) <= 5):
        return jsonify({'error': 'rating 1-5 required'}), 400
    sb = get_admin_client()
    sb.table('helpdesk_tickets').update({'resident_rating': int(rating), 'resident_feedback': data.get('feedback')}).eq('id', ticket_id).eq('flat_id', g.flat_id).execute()
    return jsonify({'rated': True})

@helpdesk_bp.get('/<ticket_id>/updates')
@require_auth
def ticket_updates(ticket_id):
    sb = get_admin_client()
    return jsonify(sb.table('ticket_updates').select('*, user_profiles(full_name)').eq('ticket_id', ticket_id).order('created_at').execute().data)
