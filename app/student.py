"""
Student-facing routes — browse events, subscribe, unsubscribe.

No login required. Students interact via public pages.
"""

import re
from datetime import datetime, date

from flask import Blueprint, render_template, redirect, url_for, flash, request

from app.extensions import db
from app.models import Event, Subscription, utc_now
from app.helpers import generate_unsubscribe_token

student_bp = Blueprint("student", __name__)

# Phone validation: must start with +, followed by 10-15 digits
PHONE_REGEX = re.compile(r"^\+\d{10,15}$")


@student_bp.route("/")
def events():
    """List upcoming, non-cancelled events ordered by date."""
    upcoming = (
        Event.query
        .filter(Event.is_cancelled == False, Event.event_date >= date.today())
        .order_by(Event.event_date.asc(), Event.event_time.asc())
        .all()
    )
    return render_template("student/events.html", events=upcoming)


@student_bp.route("/events/<int:event_id>")
def event_detail(event_id):
    """Show event details and the subscription form."""
    event = db.get_or_404(Event, event_id)
    return render_template("student/event_detail.html", event=event)


@student_bp.route("/events/<int:event_id>/subscribe", methods=["POST"])
def subscribe(event_id):
    """
    Handle subscription form submission.

    Validates:
    - Event exists and is not cancelled
    - Name is 2-100 characters
    - Phone starts with + and has 10-15 digits
    - Consent checkbox was checked
    - Not already subscribed (same phone + same event)
    """
    event = db.get_or_404(Event, event_id)

    # Can't subscribe to cancelled events
    if event.is_cancelled:
        flash("This event has been cancelled.", "warning")
        return redirect(url_for("student.event_detail", event_id=event.id))

    # Extract and clean form data
    name = request.form.get("student_name", "").strip()
    phone = request.form.get("phone_number", "").strip()
    consent = request.form.get("consent") == "on"

    # --- Validation ---
    errors = []

    if not name or len(name) < 2 or len(name) > 100:
        errors.append("Name must be between 2 and 100 characters.")

    if not phone:
        errors.append("Phone number is required.")
    elif not PHONE_REGEX.match(phone):
        errors.append(
            "Phone number must start with + followed by your country code "
            "and number (10-15 digits total). Example: +919876543210"
        )

    if not consent:
        errors.append(
            "You must consent to receiving event reminders by checking the box."
        )

    if errors:
        for error in errors:
            flash(error, "danger")
        return render_template(
            "student/event_detail.html",
            event=event,
            form_name=name,
            form_phone=phone,
        )

    # --- Duplicate check ---
    existing = Subscription.query.filter_by(
        event_id=event.id, phone_number=phone
    ).first()

    if existing:
        if existing.is_active:
            flash("You're already subscribed to this event!", "info")
        else:
            # Re-activate a previously unsubscribed subscription
            existing.is_active = True
            existing.student_name = name
            existing.consent_given = True
            existing.unsubscribed_at = None
            db.session.commit()
            flash("Welcome back! Your subscription has been re-activated.", "success")

        return redirect(url_for("student.event_detail", event_id=event.id))

    # --- Create subscription ---
    subscription = Subscription(
        event_id=event.id,
        student_name=name,
        phone_number=phone,
        consent_given=True,
        is_active=True,
        unsubscribe_token=generate_unsubscribe_token(),
    )
    db.session.add(subscription)
    db.session.commit()

    return render_template(
        "student/subscribe_success.html",
        event=event,
        subscription=subscription,
    )


@student_bp.route("/unsubscribe/<token>", methods=["GET", "POST"])
def unsubscribe(token):
    """
    Unsubscribe page using an unguessable token.

    GET: show confirmation page
    POST: deactivate the subscription
    """
    subscription = Subscription.query.filter_by(unsubscribe_token=token).first_or_404()

    if request.method == "POST":
        if subscription.is_active:
            subscription.is_active = False
            subscription.unsubscribed_at = utc_now()
            db.session.commit()
            flash("You have been unsubscribed. You will no longer receive reminders.", "success")
        else:
            flash("You were already unsubscribed.", "info")

        return redirect(url_for("student.events"))

    return render_template(
        "student/unsubscribe.html",
        subscription=subscription,
        event=subscription.event,
    )
