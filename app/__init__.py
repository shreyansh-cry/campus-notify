"""
CampusNotify — Flask Application Factory.

Creates and configures the Flask app. Call create_app() with a config name
('development', 'testing', 'production') to get a fully-wired app instance.
"""

import os
import logging

from flask import Flask
from dotenv import load_dotenv

from app.config import config_by_name
from app.extensions import db, login_manager, csrf


def create_app(config_name=None):
    """
    Application factory.

    Steps:
    1. Load .env file for environment variables
    2. Create Flask app and apply configuration
    3. Initialize extensions (database, login, CSRF)
    4. Register blueprints (student, auth, organizer, webhooks)
    5. Register CLI commands (init-db, create-organizer, seed-demo)
    6. Set up the user loader for Flask-Login
    7. Register template context processors
    """
    # Load .env before reading config
    load_dotenv()

    if config_name is None:
        config_name = os.environ.get("FLASK_CONFIG", "development")

    app = Flask(__name__)
    app.config.from_object(config_by_name[config_name])
    if os.environ.get("FLASK_SECRET_KEY"):
        app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY")

    # Validate production startup configuration
    if config_name == "production":
        secret_key = app.config.get("SECRET_KEY")
        if not secret_key or secret_key in ("dev-secret-change-me", "change-me-to-a-random-string"):
            raise ValueError("FLASK_SECRET_KEY must be set to a secure, non-default value in production.")

    # Set up basic logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Support reverse proxies for accurate Twilio webhook URL validation
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # --- Initialize extensions ---
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    from app.extensions import limiter
    limiter.init_app(app)

    # --- User loader for Flask-Login ---
    from app.models import Organizer

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Organizer, int(user_id))

    # --- Register blueprints ---
    from app.student import student_bp
    from app.auth import auth_bp
    from app.organizer import organizer_bp
    from app.webhooks import webhooks_bp

    app.register_blueprint(student_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(organizer_bp)
    app.register_blueprint(webhooks_bp)

    # --- Register CLI commands ---
    from app.commands import (
        init_db_command,
        create_organizer_command,
        reset_password_command,
        seed_demo_command,
    )

    app.cli.add_command(init_db_command)
    app.cli.add_command(create_organizer_command)
    app.cli.add_command(reset_password_command)
    app.cli.add_command(seed_demo_command)

    # --- Template context processor ---
    # Makes helper functions available in all templates
    from app.helpers import mask_phone, format_event_datetime

    @app.context_processor
    def inject_helpers():
        return {
            "mask_phone": mask_phone,
            "format_event_datetime": format_event_datetime,
            "messaging_mode": app.config.get("MESSAGING_MODE", "demo"),
        }

    # --- Error handlers ---
    @app.errorhandler(404)
    def not_found(e):
        return (
            '<div style="text-align:center;padding:80px;font-family:Inter,sans-serif">'
            '<h1 style="color:#2563EB">404</h1>'
            "<p>Page not found.</p>"
            '<a href="/" style="color:#2563EB">← Back to events</a></div>'
        ), 404

    @app.errorhandler(500)
    def server_error(e):
        return (
            '<div style="text-align:center;padding:80px;font-family:Inter,sans-serif">'
            '<h1 style="color:#dc3545">500</h1>'
            "<p>Something went wrong. Please try again.</p>"
            '<a href="/" style="color:#2563EB">← Back to events</a></div>'
        ), 500

    return app
