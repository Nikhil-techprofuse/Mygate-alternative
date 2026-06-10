from supabase import create_client, Client
from .config import Config

_client: Client = None
_admin_client: Client = None

def get_client() -> Client:
    """Anon client — respects RLS. Use for user-context queries."""
    global _client
    if _client is None:
        _client = create_client(Config.SUPABASE_URL, Config.SUPABASE_ANON_KEY)
    return _client

def get_admin_client() -> Client:
    """Service-role client — bypasses RLS. Use only in Flask backend routes."""
    global _admin_client
    if _admin_client is None:
        _admin_client = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)
    return _admin_client
