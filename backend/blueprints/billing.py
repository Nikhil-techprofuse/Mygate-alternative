from flask import Blueprint, request, jsonify, g
from ..supabase_client import get_admin_client
from ..utils.auth_middleware import require_auth, require_role

billing_bp = Blueprint('billing', __name__)

@billing_bp.get('/heads')
@require_auth
def list_billing_heads():
    sb = get_admin_client()
    return jsonify(sb.table('billing_heads').select('*').eq('society_id', g.society_id).execute().data)

@billing_bp.post('/heads')
@require_auth
@require_role('super_admin', 'committee_member')
def create_billing_head():
    data = request.get_json(silent=True) or {}
    if not data.get('name'):
        return jsonify({'error': 'name required'}), 400
    sb = get_admin_client()
    result = sb.table('billing_heads').insert({
        'society_id': g.society_id, 'name': data['name'],
        'is_gst_applicable': data.get('is_gst_applicable', False),
        'gst_percent': data.get('gst_percent', 0),
        'is_recurring': data.get('is_recurring', True),
        'frequency': data.get('frequency', 'monthly'),
        'calculation_type': data.get('calculation_type', 'fixed'),
        'amount': data.get('amount'), 'target': data.get('target', 'all'),
    }).execute()
    return jsonify(result.data[0]), 201

@billing_bp.get('/invoices')
@require_auth
def list_invoices():
    sb = get_admin_client()
    q = sb.table('invoices').select('*, invoice_items(*), flats(flat_number)')
    if g.role in ('resident', 'tenant'):
        q = q.eq('flat_id', g.flat_id)
    else:
        q = q.eq('society_id', g.society_id)
        if request.args.get('status'):
            q = q.eq('status', request.args['status'])
    return jsonify(q.order('created_at', desc=True).execute().data)

@billing_bp.get('/invoices/<invoice_id>')
@require_auth
def get_invoice(invoice_id):
    sb = get_admin_client()
    result = sb.table('invoices').select('*, invoice_items(*, billing_heads(name))').eq('id', invoice_id).single().execute()
    if not result.data:
        return jsonify({'error': 'Not found'}), 404
    if g.role in ('resident', 'tenant') and result.data['flat_id'] != g.flat_id:
        return jsonify({'error': 'Forbidden'}), 403
    return jsonify(result.data)

@billing_bp.get('/dues')
@require_auth
def get_dues():
    sb = get_admin_client()
    q = sb.table('invoices').select('id, invoice_number, total_amount, due_date, status').eq('status', 'unpaid')
    if g.role in ('resident', 'tenant'):
        q = q.eq('flat_id', g.flat_id)
    else:
        q = q.eq('society_id', g.society_id)
    return jsonify(q.execute().data)

@billing_bp.get('/payments')
@require_auth
def list_payments():
    sb = get_admin_client()
    q = sb.table('payments').select('*, invoices(invoice_number)')
    if g.role in ('resident', 'tenant'):
        q = q.eq('flat_id', g.flat_id)
    return jsonify(q.order('created_at', desc=True).execute().data)

@billing_bp.get('/expenses')
@require_auth
@require_role('super_admin', 'committee_member')
def list_expenses():
    sb = get_admin_client()
    return jsonify(sb.table('expenses').select('*').eq('society_id', g.society_id).order('expense_date', desc=True).execute().data)

@billing_bp.post('/expenses')
@require_auth
@require_role('super_admin', 'committee_member')
def add_expense():
    data = request.get_json(silent=True) or {}
    if not data.get('amount') or not data.get('category'):
        return jsonify({'error': 'amount and category required'}), 400
    sb = get_admin_client()
    result = sb.table('expenses').insert({
        'society_id': g.society_id, 'recorded_by': g.user_id,
        'category': data['category'], 'description': data.get('description'),
        'amount': data['amount'], 'vendor_name': data.get('vendor_name'),
        'receipt_url': data.get('receipt_url'), 'gst_amount': data.get('gst_amount', 0),
        'tds_amount': data.get('tds_amount', 0), 'expense_date': data.get('expense_date'),
    }).execute()
    return jsonify(result.data[0]), 201
