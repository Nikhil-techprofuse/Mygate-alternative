import os
import json
import logging
import requests
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Path for Google Group configuration file
CONFIG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'google_group_config.json'))

DEFAULT_CONFIG = {
    "group_email": "security-block-a@yoursociety.com",
    "integration_mode": "mock",
    "service_account_json": "",
    "mock_members": [
        {"email": "guard1@gmail.com", "name": "Rajan Kumar", "gate_id": "GATE-A"},
        {"email": "guard2@gmail.com", "name": "Suresh Pal", "gate_id": "GATE-B"}
    ]
}


def load_config():
    """Loads Google Group settings from JSON file."""
    if not os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'w') as f:
                json.dump(DEFAULT_CONFIG, f, indent=2)
            return DEFAULT_CONFIG
        except Exception as e:
            logger.error(f"Failed to create default Google Group config: {e}")
            return DEFAULT_CONFIG

    try:
        with open(CONFIG_PATH, 'r') as f:
            config = json.load(f)
            # Ensure all keys exist
            for key, val in DEFAULT_CONFIG.items():
                if key not in config:
                    config[key] = val
            return config
    except Exception as e:
        logger.error(f"Failed to read Google Group config: {e}")
        return DEFAULT_CONFIG


def save_config(config):
    """Saves Google Group settings to JSON file."""
    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Failed to save Google Group config: {e}")
        return False


def get_group_members():
    """
    Fetches the list of members in the Google Group.
    If mode is 'mock', returns simulated members from the config.
    If mode is 'real', queries the Google Workspace Directory API.
    """
    config = load_config()
    mode = config.get("integration_mode", "mock")
    group_email = config.get("group_email", "security-block-a@yoursociety.com")

    if mode == "mock":
        return config.get("mock_members", [])

    # Real mode: authenticate and fetch from Google API
    service_account_str = config.get("service_account_json", "")
    if not service_account_str:
        raise ValueError("Service Account JSON is not configured. Please supply it in Settings.")

    try:
        service_account_info = json.loads(service_account_str)
    except Exception as e:
        raise ValueError(f"Invalid Service Account JSON format: {e}")

    try:
        from google.oauth2 import service_account
        import google.auth.transport.requests

        scopes = ['https://www.googleapis.com/auth/admin.directory.group.member.readonly']
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info, scopes=scopes
        )

        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        token = credentials.token

        url = f"https://admin.googleapis.com/admin/directory/v1/groups/{group_email}/members"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }

        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            raise Exception(f"Google API returned status {response.status_code}: {response.text}")

        data = response.json()
        members = []
        for member in data.get('members', []):
            email = member.get('email')
            if email:
                members.append({
                    "email": email.lower(),
                    "name": member.get('name', 'Google Group Guard'),
                    "gate_id": "GATE-A"
                })
        return members
    except Exception as e:
        logger.error(f"Error calling Google Directory API: {e}")
        raise e


def is_email_in_google_group(email):
    """Helper to check if a single email belongs to the Google Group."""
    email_clean = email.strip().lower()
    try:
        members = get_group_members()
        return any(m.get('email', '').strip().lower() == email_clean for m in members)
    except Exception:
        # Fallback to local DB check if API fails during request, or return false
        return False


def sync_google_group_to_db(app):
    """
    Compares Google Group members with the database `authorized_guards` table.
    Deactivates any guard who was removed, and adds/activates new ones.
    """
    try:
        with app.app_context():
            from ..supabase_client import get_admin_client
            sb = get_admin_client()

            # 1. Fetch current Google Group members
            try:
                group_members = get_group_members()
            except Exception as e:
                logger.error(f"Google Group sync skipped due to fetch error: {e}")
                return {"success": False, "error": f"Failed to fetch members: {str(e)}"}

            group_emails = {m.get('email', '').strip().lower() for m in group_members if m.get('email')}

            # 2. Fetch all authorized guards from DB
            db_res = sb.table('authorized_guards').select('*').execute()
            db_guards = db_res.data if db_res else []

            # Track changes for reporting
            deactivated = []
            activated = []
            added = []

            # 3. Check for guards to deactivate or re-activate
            for guard in db_guards:
                guard_email = guard['email'].strip().lower()
                guard_id = guard['id']
                is_active = guard.get('active', True)

                if guard_email not in group_emails:
                    if is_active:
                        # Deactivate in authorized_guards table
                        sb.table('authorized_guards').update({'active': False}).eq('id', guard_id).execute()
                        deactivated.append(guard_email)
                        logger.info(f"Deactivated guard {guard_email} (removed from Google Group)")

                        # Force deactivate user profile in user_profiles to block active sessions instantly
                        try:
                            profile_check = sb.table('user_profiles').select('id').eq('email', guard_email).execute()
                            if profile_check.data:
                                for p in profile_check.data:
                                    sb.table('user_profiles').update({'is_active': False}).eq('id', p['id']).execute()
                        except Exception as pe:
                            logger.error(f"Could not update user_profile for {guard_email}: {pe}")
                else:
                    if not is_active:
                        # Re-activate in authorized_guards
                        sb.table('authorized_guards').update({'active': True}).eq('id', guard_id).execute()
                        activated.append(guard_email)
                        logger.info(f"Re-activated guard {guard_email} (added back to Google Group)")

                        # Re-activate user profile
                        try:
                            profile_check = sb.table('user_profiles').select('id').eq('email', guard_email).execute()
                            if profile_check.data:
                                for p in profile_check.data:
                                    sb.table('user_profiles').update({'is_active': True}).eq('id', p['id']).execute()
                        except Exception as pe:
                            logger.error(f"Could not reactivate user_profile for {guard_email}: {pe}")

            # 4. Add new members from Google Group to DB
            db_emails = {g['email'].strip().lower() for g in db_guards}
            for member in group_members:
                m_email = member.get('email', '').strip().lower()
                if m_email and m_email not in db_emails:
                    # Insert new guard
                    sb.table('authorized_guards').insert({
                        'email': m_email,
                        'name': member.get('name', 'Google Group Guard'),
                        'gate_id': member.get('gate_id', 'GATE-A'),
                        'active': True
                    }).execute()
                    added.append(m_email)
                    logger.info(f"Added new authorized guard: {m_email}")

            return {
                "success": True,
                "deactivated": deactivated,
                "activated": activated,
                "added": added,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

    except Exception as e:
        logger.error(f"Background Google Group sync failed: {e}")
        return {"success": False, "error": str(e)}
