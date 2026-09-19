"""
Authentication routes — organizer login and logout.

Uses Flask-Login for session management. Only one organizer account exists,
created via the 'flask create-organizer' CLI command.
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user

from app.models import Organizer
from app.extensions import limiter

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/organizer/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def login():
    """Show the login form and handle login attempts."""
    # Already logged in? Go to dashboard.
    if current_user.is_authenticated:
        return redirect(url_for("organizer.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        organizer = Organizer.query.filter_by(username=username).first()

        if organizer and organizer.check_password(password):
            login_user(organizer)
            flash("Logged in successfully.", "success")

            # Redirect to the page they originally wanted (if any)
            next_page = request.args.get("next")
            return redirect(next_page or url_for("organizer.dashboard"))

        flash("Invalid username or password.", "danger")

    return render_template("organizer/login.html")


@auth_bp.route("/organizer/logout", methods=["POST"])
@login_required
def logout():
    """Log the organizer out and redirect to the home page."""
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for("student.events"))
