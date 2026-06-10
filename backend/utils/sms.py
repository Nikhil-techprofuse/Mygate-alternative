import requests
from flask import current_app

def send_sms(phone: str, message: str) -> bool:
    """Send SMS via MSG91. Returns True on success."""
    auth_key = current_app.config.get('MSG91_AUTH_KEY')
    if not auth_key:
        current_app.logger.warning('MSG91_AUTH_KEY not configured — SMS skipped')
        return False
    try:
        resp = requests.post(
            'https://api.msg91.com/api/v5/flow/',
            json={
                'template_id': current_app.config.get('MSG91_TEMPLATE_ID'),
                'short_url': '0',
                'mobiles': phone,
                'VAR1': message,
            },
            headers={
                'authkey': auth_key,
                'Content-Type': 'application/json',
            },
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        current_app.logger.error(f'SMS send failed: {e}')
        return False
