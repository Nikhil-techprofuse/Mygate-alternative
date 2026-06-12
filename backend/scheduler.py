from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import logging

logger = logging.getLogger(__name__)


from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import logging

logger = logging.getLogger(__name__)


def check_delivery_overstay(app):
    """Fires every 5 min — marks deliveries that have overstayed and sets alert flag."""
    try:
        with app.app_context():
            from .supabase_client import get_admin_client
            from datetime import datetime, timezone, timedelta
            sb  = get_admin_client()
            now = datetime.now(timezone.utc)
            threshold_minutes = 30
            cutoff = (now - timedelta(minutes=threshold_minutes)).isoformat()
            deliveries = (
                sb.table('deliveries')
                .select('id, flat_id, society_id')
                .eq('status', 'allowed_in')
                .eq('overstay_alert_sent', False)
                .lte('entry_time', cutoff)
                .execute()
            )
            for d in (deliveries.data or []):
                sb.table('deliveries').update({'overstay_alert_sent': True, 'status': 'overstay'}).eq('id', d['id']).execute()
                logger.info(f'Overstay alert: delivery {d["id"]} for flat {d["flat_id"]}')
    except Exception as e:
        logger.warning(f'check_delivery_overstay skipped: {e}')


def check_sla_breaches(app):
    """Hourly — marks helpdesk tickets that have breached SLA."""
    try:
        with app.app_context():
            from .supabase_client import get_admin_client
            from datetime import datetime, timezone, timedelta
            sb  = get_admin_client()
            now = datetime.now(timezone.utc)
            open_tickets = (
                sb.table('helpdesk_tickets')
                .select('id, created_at, sla_hours')
                .in_('status', ['open', 'in_progress'])
                .eq('sla_breached', False)
                .execute()
            )
            for ticket in (open_tickets.data or []):
                created = datetime.fromisoformat(ticket['created_at'].replace('Z', '+00:00'))
                sla_deadline = created + timedelta(hours=ticket.get('sla_hours') or 24)
                if now > sla_deadline:
                    sb.table('helpdesk_tickets').update({'sla_breached': True}).eq('id', ticket['id']).execute()
                    logger.info(f'SLA breached: ticket {ticket["id"]}')
    except Exception as e:
        logger.warning(f'check_sla_breaches skipped: {e}')


def generate_monthly_invoices(app):
    """Runs on 1st of each month — creates invoices for all recurring billing heads."""
    try:
        with app.app_context():
            from .supabase_client import get_admin_client
            from datetime import datetime, date
            import calendar
            sb   = get_admin_client()
            today = date.today()
            period_start = today.replace(day=1).isoformat()
            last_day     = calendar.monthrange(today.year, today.month)[1]
            period_end   = today.replace(day=last_day).isoformat()
            due_date     = today.replace(day=last_day).isoformat()

            societies = sb.table('societies').select('id').execute().data or []
            for society in societies:
                sid = society['id']
                heads = sb.table('billing_heads').select('*').eq('society_id', sid).eq('is_recurring', True).eq('is_active', True).eq('frequency', 'monthly').execute().data or []
                if not heads:
                    continue
                flats = sb.table('flats').select('id, area_sqft').eq('society_id', sid).execute().data or []
                for flat in flats:
                    total  = 0
                    gst    = 0
                    items  = []
                    for head in heads:
                        amount = float(head.get('amount') or 0)
                        if head['calculation_type'] == 'area_based':
                            amount = amount * float(flat.get('area_sqft') or 0)
                        g_amt = round(amount * float(head.get('gst_percent') or 0) / 100, 2) if head.get('is_gst_applicable') else 0
                        items.append({'billing_head_id': head['id'], 'description': head['name'], 'amount': amount, 'gst_amount': g_amt})
                        total += amount
                        gst   += g_amt

                    existing = sb.table('invoices').select('id').eq('flat_id', flat['id']).eq('period_start', period_start).maybe_single().execute()
                    if existing.data:
                        continue

                    inv_number = f"INV-{sid[:8].upper()}-{flat['id'][:6].upper()}-{today.strftime('%Y%m')}"
                    invoice = sb.table('invoices').insert({
                        'society_id': sid, 'flat_id': flat['id'],
                        'invoice_number': inv_number, 'period_start': period_start,
                        'period_end': period_end, 'total_amount': round(total + gst, 2),
                        'gst_amount': round(gst, 2), 'due_date': due_date,
                    }).execute()
                    inv_id = invoice.data[0]['id']
                    for item in items:
                        item['invoice_id'] = inv_id
                        sb.table('invoice_items').insert(item).execute()
                    logger.info(f'Invoice generated: {inv_number}')
    except Exception as e:
        logger.warning(f'generate_monthly_invoices skipped: {e}')


def cleanup_expired_visitor_invites(app):
    """Every 15 min — remove visitor OTP invites past valid_until."""
    try:
        with app.app_context():
            from .supabase_client import get_admin_client
            from .blueprints.visitors import cleanup_expired_visitor_otps
            sb = get_admin_client()
            count = cleanup_expired_visitor_otps(sb)
            if count:
                logger.info(f'Removed {count} expired visitor OTP invite(s)')
    except Exception as e:
        logger.warning(f'cleanup_expired_visitor_invites skipped: {e}')


def cancel_unpaid_bookings(app):
    """Every 35 min — cancel amenity bookings not paid within 30 min."""
    try:
        with app.app_context():
            from .supabase_client import get_admin_client
            from datetime import datetime, timezone, timedelta
            sb  = get_admin_client()
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
            result = (
                sb.table('bookings')
                .select('id')
                .eq('status', 'pending_payment')
                .lte('created_at', cutoff)
                .execute()
            )
            for b in (result.data or []):
                sb.table('bookings').update({'status': 'cancelled'}).eq('id', b['id']).execute()
                logger.info(f'Booking auto-cancelled: {b["id"]}')
    except Exception as e:
        logger.warning(f'cancel_unpaid_bookings skipped: {e}')


def init_scheduler(app):
    scheduler = BackgroundScheduler(timezone='Asia/Kolkata')

    scheduler.add_job(
        func=lambda: check_delivery_overstay(app),
        trigger=IntervalTrigger(minutes=5),
        id='delivery_overstay',
        replace_existing=True,
    )
    scheduler.add_job(
        func=lambda: check_sla_breaches(app),
        trigger=IntervalTrigger(hours=1),
        id='sla_breach_check',
        replace_existing=True,
    )
    scheduler.add_job(
        func=lambda: generate_monthly_invoices(app),
        trigger=CronTrigger(day=1, hour=0, minute=5),
        id='monthly_invoices',
        replace_existing=True,
    )
    scheduler.add_job(
        func=lambda: cancel_unpaid_bookings(app),
        trigger=IntervalTrigger(minutes=35),
        id='cancel_unpaid_bookings',
        replace_existing=True,
    )
    scheduler.add_job(
        func=lambda: cleanup_expired_visitor_invites(app),
        trigger=IntervalTrigger(minutes=15),
        id='cleanup_expired_visitor_invites',
        replace_existing=True,
    )

    scheduler.start()
    logger.info('APScheduler started with 5 jobs')
    return scheduler
