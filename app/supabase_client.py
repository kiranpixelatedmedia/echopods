from supabase import create_client, Client
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

def get_supabase_client() -> Client | None:
    """
    Returns an initialized Supabase client using credentials from Django settings.
    Returns None if credentials are missing.
    """
    url = getattr(settings, 'SUPABASE_URL', None)
    key = getattr(settings, 'SUPABASE_KEY', None)

    if not url or not key:
        logger.warning("Supabase URL or Key is missing from settings. Supabase features will be disabled.")
        return None

    try:
        return create_client(url, key)
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {e}")
        return None

# Helper instance that can be imported directly
supabase: Client | None = get_supabase_client()
