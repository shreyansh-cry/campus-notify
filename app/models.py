"""
Database models for CampusNotify.

Four tables:
- Organizer: single admin account for managing events
- Event: club events with date, time, location
- Subscription: students subscribing to event reminders
- Notification: record of each SMS sent (or attempted)
"""

from datetime import datetime, date, time, timezone

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db
from app.helpers import generate_unsubscribe_token


def utc_now():
    """Return timezone-naive UTC datetime without invoking deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Organizer — the single admin user who manages events and sends reminders
# ---------------------------------------------------------------------------

class Organizer(UserMixin, db.Model):
    """
    Single organizer account.  Created via the 'flask create-organizer' CLI
    command — never hardcoded.
    """
    __tablename__ = "organizer"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now)

    # Relationship: an organizer can create many events
    events = db.relationship("Event", backref="organizer", lazy="dynamic")

    def set_password(self, password: str):
        """Hash and store a plaintext password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Verify a plaintext password against the stored hash."""
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<Organizer {self.username}>"


# ---------------------------------------------------------------------------
# Event — a club event that students can subscribe to
# ---------------------------------------------------------------------------

class Event(db.Model):
    """
    A club event.  Events are never deleted — they can be cancelled
    (is_cancelled=True) so we keep the history.
    """
    __tablename__ = "event"

    id = db.Column(db.Integer, primary_key=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey("organizer.id"), nullable=False)

    title = db.Column(db.String(200), nullable=False)
    club_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    event_date = db.Column(db.Date, nullable=False)
    event_time = db.Column(db.Time, nullable=True)
    location = db.Column(db.String(200), nullable=True)

    is_cancelled = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    subscriptions = db.relationship("Subscription", backref="event", lazy="dynamic")

    @property
    def active_subscriber_count(self) -> int:
        """Count of students who are still actively subscribed."""
        return self.subscriptions.filter_by(is_active=True).count()

    @property
    def is_upcoming(self) -> bool:
        """True if the event date is today or in the future."""
        return self.event_date >= date.today()

    def __repr__(self):
        return f"<Event {self.title!r}>"


# ---------------------------------------------------------------------------
# Subscription — a student subscribing to an event's reminders
# ---------------------------------------------------------------------------

class Subscription(db.Model):
    """
    A student's subscription to receive reminders for a specific event.

    Key constraints:
    - UNIQUE(event_id, phone_number): prevents duplicate subscriptions
    - consent_given must be True (validated in the route)
    - unsubscribe_token: random UUID used in unsubscribe links
    """
    __tablename__ = "subscription"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)

    student_name = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    consent_given = db.Column(db.Boolean, default=False, nullable=False)

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    unsubscribe_token = db.Column(
        db.String(64), unique=True, nullable=False, default=generate_unsubscribe_token
    )

    created_at = db.Column(db.DateTime, default=utc_now)
    unsubscribed_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    notifications = db.relationship("Notification", backref="subscription", lazy="dynamic")

    # Prevent the same phone from subscribing to the same event twice
    __table_args__ = (
        db.UniqueConstraint("event_id", "phone_number", name="uq_event_phone"),
    )

    def __repr__(self):
        return f"<Subscription event={self.event_id} phone=****{self.phone_number[-4:]}>"


# ---------------------------------------------------------------------------
# Notification — record of an SMS sent (or attempted) to a subscriber
# ---------------------------------------------------------------------------

class Notification(db.Model):
    """
    One notification record per recipient per reminder type.

    The UNIQUE constraint on (subscription_id, reminder_type) prevents
    duplicate reminders from repeated button clicks.

    Status progression:
      pending → sent → delivered  (happy path)
      pending → sent → failed     (provider reported failure)
      pending → failed             (couldn't even submit to provider)
      pending → unknown            (ambiguous network timeout)
    """
    __tablename__ = "notification"

    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(
        db.Integer, db.ForeignKey("subscription.id"), nullable=False
    )

    # 'standard' for now; extensible to '24h_before', '1h_before' later
    reminder_type = db.Column(db.String(30), default="standard", nullable=False)

    # Status tracking
    status = db.Column(db.String(20), default="pending", nullable=False)
    provider_message_id = db.Column(db.String(64), nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

    # Prevent duplicate reminders: one standard reminder per subscription
    __table_args__ = (
        db.UniqueConstraint(
            "subscription_id", "reminder_type", name="uq_subscription_reminder"
        ),
    )

    # Define which statuses are "final" — webhooks should not overwrite these
    FINAL_STATUSES = {"delivered", "failed", "undelivered"}

    # Status ranking for progression (higher = more final)
    STATUS_RANK = {
        "pending": 0,
        "sent": 1,
        "queued": 1,
        "delivered": 2,
        "failed": 2,
        "undelivered": 2,
        "unknown": 1,
    }

    def can_update_to(self, new_status: str) -> bool:
        """
        Check if the notification status can advance to new_status.

        Rules:
        - Never overwrite a final status (delivered, failed, undelivered)
        - Only advance to a status with equal or higher rank
        """
        if self.status in self.FINAL_STATUSES:
            return False
        current_rank = self.STATUS_RANK.get(self.status, 0)
        new_rank = self.STATUS_RANK.get(new_status, 0)
        return new_rank >= current_rank

    def __repr__(self):
        return f"<Notification sub={self.subscription_id} status={self.status}>"
