"""
Flask extension instances.

Created here (without an app) so that models.py, blueprints, and other
modules can import them without circular-import issues.  The app factory
calls ext.init_app(app) to bind each extension to the actual Flask app.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Database ORM
db = SQLAlchemy()

# Rate limiting
limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")

# Session-based authentication
login_manager = LoginManager()
login_manager.login_view = "auth.login"  # Redirect here when @login_required fails
login_manager.login_message = "Please log in to access the organizer area."
login_manager.login_message_category = "warning"

# CSRF protection for browser forms
csrf = CSRFProtect()
