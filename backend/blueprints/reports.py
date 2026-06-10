from flask import Blueprint, request, jsonify, g
from ..supabase_client import get_admin_client
from ..utils.auth_middleware import require_auth, require_role

reports_bp = Blueprint('reports', __name__)

@reports_bp.get('/visitors')
@require_auth
@require_role('super_admin', 'committee_member')
def visitor_report():
    sb = get_admin_client()
    q = sb.table('visitor_logs').select('visitor_type, approval_status, entry_time, flats(flat_number), gates(name)').eq('society_id', g.society_id)
    if request.args.get('from'):
        q = q.gte('entry_time', request.args['from'])
    if request.args.get('to'):
        q = q.lte('entry_time', request.args['to'])
    return jsonify(q.order('entry_time', desc=True).execute().data)

@reports_bp.get('/vehicles')
@require_auth
@require_role('super_admin', 'committee_member')
def vehicle_report():
    sb = get_admin_client()
    q = sb.table('vehicle_entry_logs').select('number_plate, entry_time, exit_time, is_visitor_vehicle, flats(flat_number)').eq('society_id', g.society_id)
    if request.args.get('from'):
        q = q.gte('entry_time', request.args['from'])
    if request.args.get('to'):
        q = q.lte('entry_time', request.args['to'])
    return jsonify(q.order('entry_time', desc=True).execute().data)

@reports_bp.get('/deliveries')
@require_auth
@require_role('super_admin', 'committee_member')
def delivery_report():
    sb = get_admin_client()
    return jsonify(sb.table('deliveries').select('*, flats(flat_number)').eq('society_id', g.society_id).order('entry_time', desc=True).execute().data)

@reports_bp.get('/domestic-help')
@require_auth
@require_role('super_admin', 'committee_member')
def domestic_help_report():
    sb = get_admin_client()
    q = sb.table('helper_attendance').select('*, domestic_helpers(name, helper_type), flats(flat_number)')
    if request.args.get('from'):
        q = q.gte('date', request.args['from'])
    if request.args.get('to'):
        q = q.lte('date', request.args['to'])
    return jsonify(q.execute().data)

@reports_bp.get('/kids-checkout')
@require_auth
@require_role('super_admin', 'committee_member')
def kids_checkout_report():
    sb = get_admin_client()
    return jsonify(sb.table('kids_checkout_events').select('*, flats(flat_number)').eq('society_id', g.society_id).order('created_at', desc=True).execute().data)

@reports_bp.get('/security-alerts')
@require_auth
@require_role('super_admin', 'committee_member')
def security_alert_report():
    sb = get_admin_client()
    return jsonify(sb.table('security_alerts').select('*, flats(flat_number), user_profiles!security_alerts_triggered_by_fkey(full_name)').eq('society_id', g.society_id).order('created_at', desc=True).execute().data)

@reports_bp.get('/financial')
@require_auth
@require_role('super_admin', 'committee_member')
def financial_report():
    sb = get_admin_client()
    invoices = sb.table('invoices').select('status, total_amount').eq('society_id', g.society_id).execute().data or []
    expenses = sb.table('expenses').select('amount').eq('society_id', g.society_id).execute().data or []
    total_invoiced = sum(i['total_amount'] or 0 for i in invoices)
    total_collected = sum(i['total_amount'] or 0 for i in invoices if i['status'] == 'paid')
    total_dues = sum(i['total_amount'] or 0 for i in invoices if i['status'] == 'unpaid')
    total_expenses = sum(e['amount'] or 0 for e in expenses)
    return jsonify({
        'total_invoiced': total_invoiced,
        'total_collected': total_collected,
        'total_dues': total_dues,
        'total_expenses': total_expenses,
        'net_balance': total_collected - total_expenses,
    })

@reports_bp.get('/helpdesk')
@require_auth
@require_role('super_admin', 'committee_member')
def helpdesk_report():
    sb = get_admin_client()
    return jsonify(sb.table('helpdesk_tickets').select('category, status, priority, sla_breached, resident_rating, created_at, resolved_at').eq('society_id', g.society_id).execute().data)
