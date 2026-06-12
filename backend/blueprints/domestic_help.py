from flask import Blueprint, request, jsonify, g
from datetime import datetime, timezone, date
from ..supabase_client import get_admin_client
from ..utils.auth_middleware import require_auth, require_role
from ..utils.otp import generate_numeric_otp

domestic_help_bp = Blueprint('domestic_help', __name__)


@domestic_help_bp.post('/')
@require_auth
@require_role('resident', 'tenant')
def add_helper():
    data = request.get_json(silent=True) or {}
    if not data.get('name') or not data.get('helper_type'):
        return jsonify({'error': 'name and helper_type required'}), 400
    sb = get_admin_client()
    # Generate unique passcode for this society
    while True:
        passcode = generate_numeric_otp(6)
        existing = sb.table('domestic_helpers').select('id').eq('society_id', g.society_id).eq('passcode', passcode).limit(1).execute()
        if not existing.data:
            break
    helper = sb.table('domestic_helpers').insert({
        'society_id':   g.society_id,
        'name':         data['name'],
        'phone':        data.get('phone'),
        'helper_type':  data['helper_type'],
        'photo_url':    data.get('photo_url'),
        'id_proof_url': data.get('id_proof_url'),
        'passcode':     passcode,
    }).execute()
    # Link helper to this flat
    sb.table('helper_flat_links').insert({
        'helper_id':   helper.data[0]['id'],
        'flat_id':     g.flat_id,
        'resident_id': g.user_id,
    }).execute()
    return jsonify({'helper': helper.data[0], 'passcode': passcode}), 201


@domestic_help_bp.get('/')
@require_auth
def list_helpers():
    sb = get_admin_client()
    if g.role in ('resident', 'tenant'):
        links = sb.table('helper_flat_links').select('helper_id').eq('flat_id', g.flat_id).eq('is_active', True).execute()
        ids   = [l['helper_id'] for l in (links.data or [])]
        if not ids:
            return jsonify([])
        result = sb.table('domestic_helpers').select('*').in_('id', ids).execute()
    else:
        result = sb.table('domestic_helpers').select('*').eq('society_id', g.society_id).execute()
    return jsonify(result.data)


@domestic_help_bp.post('/lookup')
@require_auth
@require_role('guard')
def lookup_passcode():
    passcode = (request.get_json(silent=True) or {}).get('passcode', '').strip()
    if not passcode:
        return jsonify({'error': 'passcode required'}), 400
    sb = get_admin_client()
    helper = (
        sb.table('domestic_helpers')
        .select('*, helper_flat_links(flat_id, flats(flat_number))')
        .eq('society_id', g.society_id)
        .eq('passcode', passcode)
        .limit(1)
        .execute()
    )
    if not helper.data:
        return jsonify({'error': 'Unknown passcode'}), 404
    helper_data = helper.data[0]
    if helper_data.get('is_blacklisted'):
        return jsonify({'error': 'Helper is blacklisted', 'helper': helper_data}), 403
    
    # Check if there's an active entry today (no exit time)
    today = date.today().isoformat()
    active_entry = (
        sb.table('helper_attendance')
        .select('id, entry_time, flat_id')
        .eq('helper_id', helper_data['id'])
        .eq('date', today)
        .is_('exit_time', 'null')
        .order('entry_time', desc=True)
        .limit(1)
        .execute()
    )
    
    helper_data['active_entry'] = active_entry.data[0] if active_entry.data else None
    return jsonify(helper_data)


@domestic_help_bp.post('/entry')
@require_auth
@require_role('guard')
def log_entry():
    data = request.get_json(silent=True) or {}
    if not data.get('passcode') or not data.get('flat_id'):
        return jsonify({'error': 'passcode and flat_id required'}), 400
    sb = get_admin_client()
    helper = sb.table('domestic_helpers').select('id').eq('society_id', g.society_id).eq('passcode', data['passcode']).limit(1).execute()
    if not helper.data:
        return jsonify({'error': 'Unknown passcode'}), 404
    now = datetime.now(timezone.utc).isoformat()
    result = sb.table('helper_attendance').insert({
        'helper_id':  helper.data[0]['id'],
        'flat_id':    data['flat_id'],
        'guard_id':   g.user_id,
        'entry_time': now,
        'date':       date.today().isoformat(),
    }).execute()
    return jsonify(result.data[0]), 201


@domestic_help_bp.patch('/attendance/<attendance_id>/exit')
@require_auth
@require_role('guard')
def log_exit(attendance_id):
    now = datetime.now(timezone.utc).isoformat()
    sb  = get_admin_client()
    sb.table('helper_attendance').update({'exit_time': now}).eq('id', attendance_id).execute()
    return jsonify({'exit_time': now})


@domestic_help_bp.get('/attendance')
@require_auth
def get_attendance():
    sb = get_admin_client()
    q  = sb.table('helper_attendance').select('*, domestic_helpers(name, helper_type, photo_url)')
    if g.role in ('resident', 'tenant'):
        q = q.eq('flat_id', g.flat_id)
    else:
        # Admin — filter by helper or date range
        if request.args.get('helper_id'):
            q = q.eq('helper_id', request.args['helper_id'])
        if request.args.get('from'):
            q = q.gte('date', request.args['from'])
        if request.args.get('to'):
            q = q.lte('date', request.args['to'])
    return jsonify(q.order('date', desc=True).execute().data)


@domestic_help_bp.post('/<helper_id>/rate')
@require_auth
@require_role('resident', 'tenant')
def rate_helper(helper_id):
    data = request.get_json(silent=True) or {}
    rating = data.get('rating')
    if not rating or not (1 <= int(rating) <= 5):
        return jsonify({'error': 'rating must be 1-5'}), 400
    sb = get_admin_client()
    sb.table('helper_ratings').insert({
        'helper_id':   helper_id,
        'flat_id':     g.flat_id,
        'resident_id': g.user_id,
        'rating':      int(rating),
        'note':        data.get('note'),
    }).execute()
    # Update avg_rating
    ratings = sb.table('helper_ratings').select('rating').eq('helper_id', helper_id).execute()
    vals = [r['rating'] for r in (ratings.data or [])]
    avg  = round(sum(vals) / len(vals), 1) if vals else 0
    sb.table('domestic_helpers').update({'avg_rating': avg}).eq('id', helper_id).execute()
    return jsonify({'avg_rating': avg})


@domestic_help_bp.post('/<helper_id>/blacklist')
@require_auth
@require_role('super_admin', 'committee_member')
def blacklist_helper(helper_id):
    reason = (request.get_json(silent=True) or {}).get('reason', '')
    sb = get_admin_client()
    sb.table('domestic_helpers').update({'is_blacklisted': True, 'blacklist_reason': reason}).eq('id', helper_id).execute()
    return jsonify({'blacklisted': True})


@domestic_help_bp.get('/directory')
@require_auth
@require_role('resident', 'tenant')
def helper_directory():
    """Top-rated helpers opt-in directory."""
    sb = get_admin_client()
    q  = sb.table('domestic_helpers').select('id, name, helper_type, photo_url, avg_rating').eq('society_id', g.society_id).eq('is_blacklisted', False).gte('avg_rating', 4).order('avg_rating', desc=True)
    if request.args.get('type'):
        q = q.eq('helper_type', request.args['type'])
    return jsonify(q.execute().data)
