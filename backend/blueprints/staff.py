from flask import Blueprint, request, jsonify, g
from ..supabase_client import get_admin_client
from ..utils.auth_middleware import require_auth, require_role

staff_bp = Blueprint('staff', __name__)

@staff_bp.get('/')
@require_auth
@require_role('super_admin', 'committee_member')
def list_staff():
    sb = get_admin_client()
    return jsonify(sb.table('staff_profiles').select('*').eq('society_id', g.society_id).eq('is_active', True).execute().data)

@staff_bp.post('/')
@require_auth
@require_role('super_admin', 'committee_member')
def add_staff():
    data = request.get_json(silent=True) or {}
    if not data.get('name') or not data.get('role'):
        return jsonify({'error': 'name and role required'}), 400
    sb = get_admin_client()
    result = sb.table('staff_profiles').insert({
        'society_id': g.society_id, 'name': data['name'], 'phone': data.get('phone'),
        'photo_url': data.get('photo_url'), 'id_proof_url': data.get('id_proof_url'),
        'role': data['role'], 'joining_date': data.get('joining_date'),
        'shift': data.get('shift'), 'monthly_salary': data.get('monthly_salary'),
    }).execute()
    return jsonify(result.data[0]), 201

@staff_bp.get('/<staff_id>/attendance')
@require_auth
@require_role('super_admin', 'committee_member')
def staff_attendance(staff_id):
    sb = get_admin_client()
    q = sb.table('staff_attendance').select('*').eq('staff_id', staff_id)
    if request.args.get('from'):
        q = q.gte('date', request.args['from'])
    if request.args.get('to'):
        q = q.lte('date', request.args['to'])
    return jsonify(q.order('date', desc=True).execute().data)

@staff_bp.post('/<staff_id>/attendance')
@require_auth
@require_role('super_admin', 'committee_member', 'guard')
def mark_attendance(staff_id):
    data = request.get_json(silent=True) or {}
    sb = get_admin_client()
    result = sb.table('staff_attendance').upsert({
        'staff_id': staff_id, 'date': data.get('date'),
        'check_in': data.get('check_in'), 'check_out': data.get('check_out'),
        'status': data.get('status', 'present'), 'marked_by': g.user_id,
    }).execute()
    return jsonify(result.data[0])

@staff_bp.post('/<staff_id>/leave')
@require_auth
def request_leave(staff_id):
    data = request.get_json(silent=True) or {}
    if not data.get('from_date') or not data.get('to_date'):
        return jsonify({'error': 'from_date and to_date required'}), 400
    sb = get_admin_client()
    result = sb.table('leave_requests').insert({
        'staff_id': staff_id, 'from_date': data['from_date'],
        'to_date': data['to_date'], 'reason': data.get('reason'),
    }).execute()
    return jsonify(result.data[0]), 201

@staff_bp.patch('/leave/<leave_id>')
@require_auth
@require_role('super_admin', 'committee_member')
def approve_leave(leave_id):
    status = (request.get_json(silent=True) or {}).get('status')
    if status not in ('approved', 'rejected'):
        return jsonify({'error': "status must be 'approved' or 'rejected'"}), 400
    sb = get_admin_client()
    sb.table('leave_requests').update({'status': status, 'reviewed_by': g.user_id}).eq('id', leave_id).execute()
    return jsonify({'status': status})
