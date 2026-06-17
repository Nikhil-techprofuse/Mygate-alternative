from supabase import create_client, Client
from .config import Config

_client: Client = None
_admin_client: Client = None

def get_client() -> Client:
    """Anon client — respects RLS. Use for user-context queries."""
    return create_client(Config.SUPABASE_URL, Config.SUPABASE_ANON_KEY)

def get_admin_client() -> Client:
    """Service-role client — bypasses RLS. Use only in Flask backend routes."""
    return create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)
