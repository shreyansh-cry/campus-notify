"""
Tests for organizer features.

Covers:
- Event CRUD (create, edit, cancel)
- Send reminders
- Idempotent sends (repeated clicks don't duplicate notifications)
- Unsubscribed students excluded from reminders
- Provider failure handling
"""

from datetime import date, time, timedelta

from app.models import Event, Notification, Subscription
from app.helpers import generate_unsubscribe_token


class TestEventManagement:
    """Verify event CRUD operations."""

    def test_create_event(self, auth_client, db_session):
        """Organizer can create a new event."""
        resp = auth_client.post("/organizer/events/new", data={
            "title": "New Workshop",
            "club_name": "Coding Club",
            "description": "Learn something new",
            "event_date": (date.today() + timedelta(days=10)).strftime("%Y-%m-%d"),
            "event_time": "14:00",
            "location": "Lab 3",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"saved successfully" in resp.data.lower()

        event = Event.query.filter_by(title="New Workshop").first()
        assert event is not None
        assert event.club_name == "Coding Club"

    def test_create_event_missing_title(self, auth_client):
        """Creating an event without a title should fail."""
        resp = auth_client.post("/organizer/events/new", data={
            "title": "",
            "club_name": "Some Club",
            "event_date": "2026-10-01",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"title is required" in resp.data.lower()

    def test_create_event_title_too_long(self, auth_client):
        """Creating an event with a title > 200 chars should fail."""
        resp = auth_client.post("/organizer/events/new", data={
            "title": "A" * 201,
            "club_name": "Some Club",
            "event_date": "2026-10-01",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"200 characters or less" in resp.data.lower()

    def test_edit_event(self, auth_client, sample_event, db_session):
        """Organizer can edit an existing event."""
        resp = auth_client.post(f"/organizer/events/{sample_event.id}/edit", data={
            "title": "Updated Workshop",
            "club_name": "Updated Club",
            "event_date": sample_event.event_date.strftime("%Y-%m-%d"),
            "event_time": "16:00",
            "location": "Room 202",
            "description": "Updated description",
        }, follow_redirects=True)
        assert resp.status_code == 200

        db_session.session.refresh(sample_event)
        assert sample_event.title == "Updated Workshop"
        assert sample_event.club_name == "Updated Club"

    def test_cancel_event(self, auth_client, sample_event, db_session):
        """Organizer can cancel an event (soft delete)."""
        resp = auth_client.post(
            f"/organizer/events/{sample_event.id}/cancel",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"cancelled" in resp.data.lower()

        db_session.session.refresh(sample_event)
        assert sample_event.is_cancelled is True

    def test_cancel_already_cancelled(self, auth_client, cancelled_event):
        """Cancelling an already cancelled event shows info message."""
        resp = auth_client.post(
            f"/organizer/events/{cancelled_event.id}/cancel",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"already cancelled" in resp.data.lower()


class TestSendReminders:
    """Verify reminder sending functionality."""

    def test_send_reminder_confirmation_page(self, auth_client, sample_event, sample_subscription):
        """GET /send should show confirmation page."""
        resp = auth_client.get(f"/organizer/events/{sample_event.id}/send")
        assert resp.status_code == 200
        assert b"Send Reminder?" in resp.data
        assert b"1 active subscriber" in resp.data

    def test_send_reminder_success(self, auth_client, sample_event, sample_subscription, db_session):
        """POST /send should create notification records and send messages."""
        resp = auth_client.post(
            f"/organizer/events/{sample_event.id}/send",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"1 sent" in resp.data.lower()

        # Verify notification was created
        notif = Notification.query.filter_by(
            subscription_id=sample_subscription.id
        ).first()
        assert notif is not None
        assert notif.status == "sent"
        assert notif.reminder_type == "standard"
        assert notif.provider_message_id is not None  # Demo mode generates a fake SID

    def test_send_reminder_idempotent(self, auth_client, sample_event, sample_subscription, db_session):
        """Clicking send twice should NOT create duplicate notifications."""
        # First send
        auth_client.post(f"/organizer/events/{sample_event.id}/send")

        # Second send — should skip (already sent)
        resp = auth_client.post(
            f"/organizer/events/{sample_event.id}/send",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"already sent" in resp.data.lower()

        # Verify only ONE notification exists
        count = Notification.query.filter_by(
            subscription_id=sample_subscription.id,
            reminder_type="standard",
        ).count()
        assert count == 1

    def test_unsubscribed_student_excluded(self, auth_client, sample_event, db_session, organizer):
        """Unsubscribed students should not receive reminders."""
        # Create an unsubscribed student
        unsub = Subscription(
            event_id=sample_event.id,
            student_name="Unsub Student",
            phone_number="+918888888888",
            consent_given=True,
            is_active=False,  # Unsubscribed!
            unsubscribe_token=generate_unsubscribe_token(),
        )
        db_session.session.add(unsub)
        db_session.session.commit()

        # Send reminders
        auth_client.post(f"/organizer/events/{sample_event.id}/send")

        # Verify no notification for unsubscribed student
        notif = Notification.query.filter_by(subscription_id=unsub.id).first()
        assert notif is None

    def test_send_reminder_for_cancelled_event(self, auth_client, cancelled_event):
        """Cannot send reminders for cancelled events."""
        resp = auth_client.post(
            f"/organizer/events/{cancelled_event.id}/send",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"cancelled" in resp.data.lower()

    def test_provider_failure_recorded(self, auth_client, sample_event, db_session, organizer):
        """Provider failures should be recorded, not crash the app."""
        # Create a subscriber whose number triggers demo failure (ends in 0000)
        fail_sub = Subscription(
            event_id=sample_event.id,
            student_name="Fail Student",
            phone_number="+911234560000",
            consent_given=True,
            is_active=True,
            unsubscribe_token=generate_unsubscribe_token(),
        )
        db_session.session.add(fail_sub)
        db_session.session.commit()

        # Send reminders
        resp = auth_client.post(
            f"/organizer/events/{sample_event.id}/send",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"failed" in resp.data.lower()

        # Verify failure was recorded
        notif = Notification.query.filter_by(subscription_id=fail_sub.id).first()
        assert notif is not None
        assert notif.status == "failed"
        assert notif.error_message is not None

    def test_no_subscribers_message(self, auth_client, db_session, organizer):
        """Sending to an event with no subscribers shows info message."""
        event = Event(
            organizer_id=organizer.id,
            title="Empty Event",
            club_name="Club",
            event_date=date.today() + timedelta(days=5),
        )
        db_session.session.add(event)
        db_session.session.commit()

        resp = auth_client.post(
            f"/organizer/events/{event.id}/send",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"no active subscribers" in resp.data.lower()


class TestDashboard:
    """Verify the organizer dashboard."""

    def test_dashboard_renders(self, auth_client):
        """Dashboard should render with counts."""
        resp = auth_client.get("/organizer/dashboard")
        assert resp.status_code == 200
        assert b"Dashboard" in resp.data

    def test_notifications_page_renders(self, auth_client):
        """Notifications page should render."""
        resp = auth_client.get("/organizer/notifications")
        assert resp.status_code == 200
        assert b"Notification History" in resp.data
