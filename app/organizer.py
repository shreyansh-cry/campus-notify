"""
Organizer routes — dashboard, event management, sending reminders.

All routes require @login_required. The organizer manages events,
views subscribers (with masked phone numbers), and sends reminders.
"""

from datetime import date, datetime

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request, current_app
)
from flask_login import login_required

from app.extensions import db
from app.models import Event, Subscription, Notification
from app.messaging import get_messaging_service
from app.helpers import build_reminder_message

from sqlalchemy.exc import IntegrityError

organizer_bp = Blueprint("organizer", __name__)


@organizer_bp.route("/organizer/dashboard")
@login_required
def dashboard():
    """Show summary counts: events, subscribers, notifications."""
    total_events = Event.query.count()
    upcoming_events = Event.query.filter(
        Event.is_cancelled == False,
        Event.event_date >= date.today()
    ).count()
    total_subscribers = Subscription.query.filter_by(is_active=True).count()
    total_notifications = Notification.query.count()

    # Recent events for quick access
    recent_events = (
        Event.query
        .order_by(Event.created_at.desc())
        .limit(5)
        .all()
    )

    return render_template(
        "organizer/dashboard.html",
        total_events=total_events,
        upcoming_events=upcoming_events,
        total_subscribers=total_subscribers,
        total_notifications=total_notifications,
        recent_events=recent_events,
        messaging_mode=current_app.config.get("MESSAGING_MODE", "demo"),
    )


@organizer_bp.route("/organizer/events")
@login_required
def event_list():
    """List all events (including cancelled and past)."""
    events = Event.query.order_by(Event.event_date.desc()).all()
    return render_template("organizer/event_list.html", events=events)


@organizer_bp.route("/organizer/events/new", methods=["GET", "POST"])
@login_required
def create_event():
    """Create a new event."""
    if request.method == "POST":
        return _save_event(event=None)

    return render_template("organizer/event_form.html", event=None)


@organizer_bp.route("/organizer/events/<int:event_id>/edit", methods=["GET", "POST"])
@login_required
def edit_event(event_id):
    """Edit an existing event."""
    event = db.get_or_404(Event, event_id)

    if request.method == "POST":
        return _save_event(event=event)

    return render_template("organizer/event_form.html", event=event)


def _save_event(event):
    """
    Shared logic for creating and editing events.
    Validates form data, creates or updates the Event record.
    """
    from flask_login import current_user

    title = request.form.get("title", "").strip()
    club_name = request.form.get("club_name", "").strip()
    description = request.form.get("description", "").strip()
    event_date_str = request.form.get("event_date", "").strip()
    event_time_str = request.form.get("event_time", "").strip()
    location = request.form.get("location", "").strip()

    # Validation
    errors = []
    if not title:
        errors.append("Event title is required.")
    elif len(title) > 200:
        errors.append("Event title must be 200 characters or less.")
        
    if not club_name:
        errors.append("Club name is required.")
    elif len(club_name) > 100:
        errors.append("Club name must be 100 characters or less.")
        
    if location and len(location) > 200:
        errors.append("Location must be 200 characters or less.")
        
    if not event_date_str:
        errors.append("Event date is required.")

    # Parse date
    parsed_date = None
    if event_date_str:
        try:
            parsed_date = datetime.strptime(event_date_str, "%Y-%m-%d").date()
        except ValueError:
            errors.append("Invalid date format. Use YYYY-MM-DD.")

    # Parse time (optional)
    parsed_time = None
    if event_time_str:
        try:
            parsed_time = datetime.strptime(event_time_str, "%H:%M").time()
        except ValueError:
            errors.append("Invalid time format. Use HH:MM.")

    if errors:
        for error in errors:
            flash(error, "danger")
        return render_template("organizer/event_form.html", event=event)

    # Create or update
    if event is None:
        event = Event(organizer_id=current_user.id)
        db.session.add(event)

    event.title = title
    event.club_name = club_name
    event.description = description
    event.event_date = parsed_date
    event.event_time = parsed_time
    event.location = location

    db.session.commit()

    action = "created" if event.id else "updated"
    flash(f"Event '{title}' saved successfully.", "success")
    return redirect(url_for("organizer.event_detail", event_id=event.id))


@organizer_bp.route("/organizer/events/<int:event_id>")
@login_required
def event_detail(event_id):
    """Show event details, subscriber list (masked phones), and notification status."""
    event = db.get_or_404(Event, event_id)
    subscriptions = event.subscriptions.order_by(Subscription.created_at.desc()).all()
    notifications = (
        Notification.query
        .join(Subscription)
        .filter(Subscription.event_id == event_id)
        .order_by(Notification.created_at.desc())
        .all()
    )

    # Standard reminders for this event
    standard_notifications = [n for n in notifications if n.reminder_type == "standard"]
    sent_sub_ids = set(n.subscription_id for n in standard_notifications)

    active_subscriptions = [s for s in subscriptions if s.is_active and s.consent_given]
    eligible_count = sum(1 for s in active_subscriptions if s.id not in sent_sub_ids)
    already_sent_count = sum(1 for s in active_subscriptions if s.id in sent_sub_ids)
    active_subscriber_count = len(active_subscriptions)

    # Detailed delivery outcome counts
    delivered_count = sum(1 for n in standard_notifications if n.status == "delivered")
    sent_count = sum(1 for n in standard_notifications if n.status == "sent")
    pending_count = sum(1 for n in standard_notifications if n.status == "pending")
    failed_count = sum(1 for n in standard_notifications if n.status in ("failed", "undelivered"))

    return render_template(
        "organizer/event_detail.html",
        event=event,
        subscriptions=subscriptions,
        notifications=notifications,
        eligible_count=eligible_count,
        already_sent_count=already_sent_count,
        already_attempted_count=len(sent_sub_ids),
        active_subscriber_count=active_subscriber_count,
        delivered_count=delivered_count,
        sent_count=sent_count,
        pending_count=pending_count,
        failed_count=failed_count,
        has_sent_reminder=(already_sent_count > 0 and eligible_count == 0),
        messaging_mode=current_app.config.get("MESSAGING_MODE", "demo"),
    )


@organizer_bp.route("/organizer/events/<int:event_id>/cancel", methods=["POST"])
@login_required
def cancel_event(event_id):
    """Soft-cancel an event (preserves history)."""
    event = db.get_or_404(Event, event_id)

    if event.is_cancelled:
        flash("This event is already cancelled.", "info")
    else:
        event.is_cancelled = True
        db.session.commit()
        flash(f"Event '{event.title}' has been cancelled.", "warning")

    return redirect(url_for("organizer.event_detail", event_id=event.id))


@organizer_bp.route("/organizer/events/<int:event_id>/send", methods=["GET", "POST"])
@login_required
def send_reminder(event_id):
    """
    Send the standard reminder for an event.

    GET:  Show confirmation page with eligible subscriber count
    POST: Actually send the reminders (one per eligible active subscriber)

    Uses database uniqueness constraint (subscription_id + reminder_type)
    to prevent duplicate sends from repeated clicks.
    """
    event = db.get_or_404(Event, event_id)

    # Guard: can't send reminders for cancelled events
    if event.is_cancelled:
        flash("Cannot send reminders for a cancelled event.", "warning")
        return redirect(url_for("organizer.event_detail", event_id=event.id))

    # Guard: can't send reminders for past events
    if not event.is_upcoming:
        flash("Cannot send reminders for past events.", "warning")
        return redirect(url_for("organizer.event_detail", event_id=event.id))

    # Subscriptions that already have a standard reminder
    sent_sub_ids = set(
        n.subscription_id for n in Notification.query
        .join(Subscription)
        .filter(
            Subscription.event_id == event_id,
            Notification.reminder_type == "standard"
        ).all()
    )

    # Active subscribers
    active_subs = event.subscriptions.filter_by(is_active=True).all()
    eligible_subs = [s for s in active_subs if s.consent_given and s.id not in sent_sub_ids]

    if request.method == "GET":
        return render_template(
            "organizer/confirm_send.html",
            event=event,
            subscriber_count=len(eligible_subs),
            already_sent_count=len(sent_sub_ids),
            total_active_count=len(active_subs),
            messaging_mode=current_app.config.get("MESSAGING_MODE", "demo"),
        )

    # POST — actually send
    if not active_subs:
        flash("No active subscribers to send reminders to.", "info")
        return redirect(url_for("organizer.event_detail", event_id=event.id))

    # If no new eligible subscribers, send nothing
    if not eligible_subs:
        flash(f"Reminders: {len(sent_sub_ids)} already sent.", "info")
        return redirect(url_for("organizer.event_detail", event_id=event.id))

    messaging = get_messaging_service()
    message_body = build_reminder_message(event)

    sent_count = 0
    failed_count = 0
    skipped_count = 0

    for sub in eligible_subs:
        # Create notification record — the UNIQUE constraint prevents duplicates
        notification = Notification(
            subscription_id=sub.id,
            reminder_type="standard",
            status="pending",
        )

        try:
            # Commit the intent BEFORE calling the external API.
            # If the database fails later, we don't accidentally send duplicates on retry.
            db.session.add(notification)
            db.session.commit()
        except IntegrityError:
            # Already sent (or pending) a standard reminder to this subscriber — skip
            db.session.rollback()
            skipped_count += 1
            continue

        # Send via messaging service
        result = messaging.send_sms(
            to=sub.phone_number,
            body=message_body,
            from_number=current_app.config.get("TWILIO_PHONE_NUMBER"),
        )

        if result["success"]:
            notification.status = "sent"
            notification.provider_message_id = result.get("provider_message_id")
            sent_count += 1
        else:
            notification.status = "failed"
            notification.error_message = result.get("error", "Unknown error")
            failed_count += 1

        try:
            db.session.commit()
        except Exception:
            # If this final commit fails, the record remains in 'pending' status in the DB,
            # accurately reflecting that we attempted a send but lost internal track of the final result.
            # A retry will hit the IntegrityError above and not duplicate the SMS.
            db.session.rollback()

    # Summary flash message
    parts = []
    if sent_count:
        parts.append(f"{sent_count} sent")
    if failed_count:
        parts.append(f"{failed_count} failed")
    if skipped_count:
        parts.append(f"{skipped_count} already sent")

    flash(f"Reminders: {', '.join(parts)}.", "success" if not failed_count else "warning")
    return redirect(url_for("organizer.event_detail", event_id=event.id))


@organizer_bp.route("/organizer/notifications")
@login_required
def notifications():
    """Show full notification history across all events."""
    all_notifications = (
        Notification.query
        .join(Subscription)
        .join(Event)
        .order_by(Notification.created_at.desc())
        .all()
    )

    return render_template(
        "organizer/notifications.html",
        notifications=all_notifications,
        messaging_mode=current_app.config.get("MESSAGING_MODE", "demo"),
    )
