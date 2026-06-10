import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

class Config:
    SUPABASE_URL          = os.getenv('SUPABASE_URL')
    SUPABASE_ANON_KEY     = os.getenv('SUPABASE_ANON_KEY')
    SUPABASE_SERVICE_KEY  = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    SECRET_KEY            = os.getenv('FLASK_SECRET_KEY', 'dev-secret-change-me')
    DEBUG                 = os.getenv('FLASK_ENV') == 'development'
    # SMS
    MSG91_AUTH_KEY        = os.getenv('MSG91_AUTH_KEY')
    MSG91_SENDER_ID       = os.getenv('MSG91_SENDER_ID', 'MYGATE')
    MSG91_TEMPLATE_ID     = os.getenv('MSG91_TEMPLATE_ID')
    # Twilio IVR
    TWILIO_ACCOUNT_SID    = os.getenv('TWILIO_ACCOUNT_SID')
    TWILIO_AUTH_TOKEN     = os.getenv('TWILIO_AUTH_TOKEN')
    TWILIO_PHONE_NUMBER   = os.getenv('TWILIO_PHONE_NUMBER')
    # Razorpay
    RAZORPAY_KEY_ID       = os.getenv('RAZORPAY_KEY_ID')
    RAZORPAY_KEY_SECRET   = os.getenv('RAZORPAY_KEY_SECRET')
    RAZORPAY_WEBHOOK_SECRET = os.getenv('RAZORPAY_WEBHOOK_SECRET')
    # VAPID (Web Push)
    VAPID_PUBLIC_KEY      = os.getenv('VAPID_PUBLIC_KEY')
    VAPID_PRIVATE_KEY     = os.getenv('VAPID_PRIVATE_KEY')
    VAPID_CLAIMS_EMAIL    = os.getenv('VAPID_CLAIMS_EMAIL')
    # Dev bypass — 3 accounts, one per portal (REMOVE IN PRODUCTION)
    DEV_TEST_PHONE        = os.getenv('DEV_TEST_PHONE', '')   # legacy alias
    DEV_TEST_OTP          = os.getenv('DEV_TEST_OTP', '')
    DEV_ADMIN_PHONE       = os.getenv('DEV_ADMIN_PHONE', os.getenv('DEV_TEST_PHONE', ''))
    DEV_ADMIN_OTP         = os.getenv('DEV_ADMIN_OTP',   os.getenv('DEV_TEST_OTP',   ''))
    DEV_GUARD_PHONE       = os.getenv('DEV_GUARD_PHONE', '')
    DEV_GUARD_OTP         = os.getenv('DEV_GUARD_OTP',   '')
    DEV_RESIDENT_PHONE    = os.getenv('DEV_RESIDENT_PHONE', '')
    DEV_RESIDENT_OTP      = os.getenv('DEV_RESIDENT_OTP',   '')
