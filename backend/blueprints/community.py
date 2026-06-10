from flask import Blueprint, request, jsonify, g
from ..supabase_client import get_admin_client
from ..utils.auth_middleware import require_auth, require_role

community_bp = Blueprint('community', __name__)

# ── Notices ───────────────────────────────────────────────────────────────────
@community_bp.get('/notices')
@require_auth
def list_notices():
    sb = get_admin_client()
    return jsonify(sb.table('notices').select('*, user_profiles(full_name)').eq('society_id', g.society_id).order('is_pinned', desc=True).order('created_at', desc=True).execute().data)

@community_bp.post('/notices')
@require_auth
@require_role('super_admin', 'committee_member')
def create_notice():
    data = request.get_json(silent=True) or {}
    if not data.get('title'):
        return jsonify({'error': 'title required'}), 400
    sb = get_admin_client()
    result = sb.table('notices').insert({'society_id': g.society_id, 'posted_by': g.user_id, 'title': data['title'], 'body': data.get('body'), 'is_pinned': data.get('is_pinned', False)}).execute()
    return jsonify(result.data[0]), 201

@community_bp.post('/notices/<notice_id>/acknowledge')
@require_auth
def acknowledge_notice(notice_id):
    sb = get_admin_client()
    sb.table('notice_acknowledgments').upsert({'notice_id': notice_id, 'resident_id': g.user_id}).execute()
    return jsonify({'acknowledged': True})

# ── Polls ─────────────────────────────────────────────────────────────────────
@community_bp.get('/polls')
@require_auth
def list_polls():
    sb = get_admin_client()
    return jsonify(sb.table('polls').select('*, poll_options(*)').eq('society_id', g.society_id).order('created_at', desc=True).execute().data)

@community_bp.post('/polls')
@require_auth
@require_role('super_admin', 'committee_member')
def create_poll():
    data = request.get_json(silent=True) or {}
    if not data.get('question') or not data.get('options'):
        return jsonify({'error': 'question and options required'}), 400
    sb = get_admin_client()
    poll = sb.table('polls').insert({'society_id': g.society_id, 'created_by': g.user_id, 'question': data['question'], 'is_secret': data.get('is_secret', False), 'ends_at': data.get('ends_at')}).execute()
    poll_id = poll.data[0]['id']
    for opt in data['options']:
        sb.table('poll_options').insert({'poll_id': poll_id, 'option_text': opt}).execute()
    return jsonify(poll.data[0]), 201

@community_bp.post('/polls/<poll_id>/vote')
@require_auth
def vote_poll(poll_id):
    option_id = (request.get_json(silent=True) or {}).get('option_id')
    if not option_id:
        return jsonify({'error': 'option_id required'}), 400
    sb = get_admin_client()
    try:
        sb.table('poll_votes').insert({'poll_id': poll_id, 'option_id': option_id, 'voter_id': g.user_id}).execute()
    except Exception:
        return jsonify({'error': 'Already voted'}), 409
    return jsonify({'voted': True})

@community_bp.get('/polls/<poll_id>/results')
@require_auth
def poll_results(poll_id):
    sb = get_admin_client()
    options = sb.table('poll_options').select('id, option_text').eq('poll_id', poll_id).execute().data
    result = []
    for opt in (options or []):
        count = len(sb.table('poll_votes').select('id').eq('option_id', opt['id']).execute().data or [])
        result.append({'option_id': opt['id'], 'option_text': opt['option_text'], 'votes': count})
    return jsonify(result)

# ── Events ────────────────────────────────────────────────────────────────────
@community_bp.get('/events')
@require_auth
def list_events():
    sb = get_admin_client()
    return jsonify(sb.table('events').select('*').eq('society_id', g.society_id).order('event_date').execute().data)

@community_bp.post('/events')
@require_auth
@require_role('super_admin', 'committee_member')
def create_event():
    data = request.get_json(silent=True) or {}
    if not data.get('title'):
        return jsonify({'error': 'title required'}), 400
    sb = get_admin_client()
    result = sb.table('events').insert({'society_id': g.society_id, 'created_by': g.user_id, 'title': data['title'], 'description': data.get('description'), 'venue': data.get('venue'), 'event_date': data.get('event_date')}).execute()
    return jsonify(result.data[0]), 201

@community_bp.post('/events/<event_id>/rsvp')
@require_auth
def rsvp_event(event_id):
    status = (request.get_json(silent=True) or {}).get('status', 'going')
    sb = get_admin_client()
    sb.table('event_rsvp').upsert({'event_id': event_id, 'resident_id': g.user_id, 'status': status}).execute()
    return jsonify({'rsvp': status})

# ── Forum ─────────────────────────────────────────────────────────────────────
@community_bp.get('/forum')
@require_auth
def list_threads():
    sb = get_admin_client()
    q = sb.table('forum_threads').select('*, user_profiles(full_name)').eq('society_id', g.society_id)
    if request.args.get('group_type'):
        q = q.eq('group_type', request.args['group_type'])
    return jsonify(q.order('created_at', desc=True).execute().data)

@community_bp.post('/forum')
@require_auth
def create_thread():
    data = request.get_json(silent=True) or {}
    if not data.get('title'):
        return jsonify({'error': 'title required'}), 400
    sb = get_admin_client()
    result = sb.table('forum_threads').insert({'society_id': g.society_id, 'created_by': g.user_id, 'title': data['title'], 'body': data.get('body'), 'group_type': data.get('group_type', 'general')}).execute()
    return jsonify(result.data[0]), 201

@community_bp.get('/forum/<thread_id>/replies')
@require_auth
def get_replies(thread_id):
    sb = get_admin_client()
    return jsonify(sb.table('forum_replies').select('*, user_profiles(full_name)').eq('thread_id', thread_id).order('created_at').execute().data)

@community_bp.post('/forum/<thread_id>/replies')
@require_auth
def add_reply(thread_id):
    body = (request.get_json(silent=True) or {}).get('body', '').strip()
    if not body:
        return jsonify({'error': 'body required'}), 400
    sb = get_admin_client()
    result = sb.table('forum_replies').insert({'thread_id': thread_id, 'posted_by': g.user_id, 'body': body}).execute()
    return jsonify(result.data[0]), 201

# ── Documents ─────────────────────────────────────────────────────────────────
@community_bp.get('/documents/society')
@require_auth
def society_docs():
    sb = get_admin_client()
    return jsonify(sb.table('society_documents').select('*').eq('society_id', g.society_id).execute().data)

@community_bp.post('/documents/society')
@require_auth
@require_role('super_admin', 'committee_member')
def upload_society_doc():
    data = request.get_json(silent=True) or {}
    if not data.get('file_url'):
        return jsonify({'error': 'file_url required'}), 400
    sb = get_admin_client()
    result = sb.table('society_documents').insert({'society_id': g.society_id, 'uploaded_by': g.user_id, 'title': data.get('title'), 'file_url': data['file_url'], 'doc_type': data.get('doc_type')}).execute()
    return jsonify(result.data[0]), 201

@community_bp.get('/documents/personal')
@require_auth
@require_role('resident', 'tenant')
def personal_docs():
    sb = get_admin_client()
    return jsonify(sb.table('personal_documents').select('*').eq('flat_id', g.flat_id).execute().data)

@community_bp.post('/documents/personal')
@require_auth
@require_role('resident', 'tenant')
def upload_personal_doc():
    data = request.get_json(silent=True) or {}
    if not data.get('file_url'):
        return jsonify({'error': 'file_url required'}), 400
    sb = get_admin_client()
    result = sb.table('personal_documents').insert({'flat_id': g.flat_id, 'uploaded_by': g.user_id, 'title': data.get('title'), 'file_url': data['file_url'], 'doc_type': data.get('doc_type', 'other')}).execute()
    return jsonify(result.data[0]), 201
