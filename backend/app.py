import os
from flask import Flask, send_from_directory
from flask_cors import CORS
from .config import Config
from .scheduler import init_scheduler

# Resolve frontend folder relative to this file's location
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'frontend')

def create_app():
    app = Flask(__name__, static_folder=None)
    app.config.from_object(Config)

    CORS(app, origins='*')

    # ── Register blueprints ───────────────────────────────────────────────────
    from .blueprints.auth           import auth_bp
    from .blueprints.visitors       import visitors_bp
    from .blueprints.vehicles       import vehicles_bp
    from .blueprints.delivery       import delivery_bp
    from .blueprints.domestic_help  import domestic_help_bp
    from .blueprints.kids_checkout  import kids_checkout_bp
    from .blueprints.security_alerts import security_alerts_bp
    from .blueprints.community      import community_bp
    from .blueprints.billing        import billing_bp
    from .blueprints.helpdesk       import helpdesk_bp
    from .blueprints.amenities      import amenities_bp
    from .blueprints.staff          import staff_bp
    from .blueprints.reports        import reports_bp
    from .blueprints.admin          import admin_bp
    from .blueprints.notifications  import notifications_bp
    from .blueprints.guards         import guards_bp

    app.register_blueprint(auth_bp,             url_prefix='/api/auth')
    app.register_blueprint(visitors_bp,         url_prefix='/api/visitors')
    app.register_blueprint(vehicles_bp,         url_prefix='/api/vehicles')
    app.register_blueprint(delivery_bp,         url_prefix='/api/delivery')
    app.register_blueprint(domestic_help_bp,    url_prefix='/api/domestic-help')
    app.register_blueprint(kids_checkout_bp,    url_prefix='/api/kids-checkout')
    app.register_blueprint(security_alerts_bp,  url_prefix='/api/security-alerts')
    app.register_blueprint(community_bp,        url_prefix='/api/community')
    app.register_blueprint(billing_bp,          url_prefix='/api/billing')
    app.register_blueprint(helpdesk_bp,         url_prefix='/api/helpdesk')
    app.register_blueprint(amenities_bp,        url_prefix='/api/amenities')
    app.register_blueprint(staff_bp,            url_prefix='/api/staff')
    app.register_blueprint(reports_bp,          url_prefix='/api/reports')
    app.register_blueprint(admin_bp,            url_prefix='/api/admin')
    app.register_blueprint(notifications_bp,    url_prefix='/api/notifications')
    app.register_blueprint(guards_bp,           url_prefix='/api/guards')

    # ── Health check ─────────────────────────────────────────────────────────
    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'app': 'MyGate API'}

    # ── Serve frontend portals ────────────────────────────────────────────────
    @app.get('/')
    def index():
        return send_from_directory(os.path.join(FRONTEND_DIR, 'resident'), 'index.html')

    @app.get('/resident')
    @app.get('/resident/')
    def resident_portal():
        return send_from_directory(os.path.join(FRONTEND_DIR, 'resident'), 'index.html')

    @app.get('/guard')
    @app.get('/guard/')
    def guard_portal():
        return send_from_directory(os.path.join(FRONTEND_DIR, 'guard'), 'index.html')

    @app.get('/admin')
    @app.get('/admin/')
    def admin_portal():
        return send_from_directory(os.path.join(FRONTEND_DIR, 'admin'), 'index.html')

    # Serve any static file from frontend/ (CSS, JS, manifests, icons, sw.js)
    @app.get('/frontend/<path:filename>')
    def frontend_static(filename):
        return send_from_directory(FRONTEND_DIR, filename)

    # Service workers must be served from the portal root path
    @app.get('/resident/sw.js')
    def resident_sw():
        return send_from_directory(os.path.join(FRONTEND_DIR, 'resident'), 'sw.js',
                                   mimetype='application/javascript')

    @app.get('/guard/sw.js')
    def guard_sw():
        return send_from_directory(os.path.join(FRONTEND_DIR, 'guard'), 'sw.js',
                                   mimetype='application/javascript')

    @app.get('/resident/manifest.json')
    def resident_manifest():
        return send_from_directory(os.path.join(FRONTEND_DIR, 'resident'), 'manifest.json')

    @app.get('/guard/manifest.json')
    def guard_manifest():
        return send_from_directory(os.path.join(FRONTEND_DIR, 'guard'), 'manifest.json')

    # ── APScheduler ──────────────────────────────────────────────────────────
    init_scheduler(app)

    return app
