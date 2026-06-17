import os
from backend.app import create_app
from backend.config import Config

print("CRITICAL DEBUG: SUPABASE_SERVICE_KEY loaded in config:", Config.SUPABASE_SERVICE_KEY[:20] if Config.SUPABASE_SERVICE_KEY else 'None')

app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=True)
