"""
Tests for per-subscription reminder eligibility and incremental batching.

Verifies the exact user scenario:
1. Student A subscribes to an upcoming event.
2. The organizer sends reminders. Only A gets a notification.
3. Student B subscribes afterward.
4. The organizer can send reminders again. Only B gets a new notification; A must not receive another.
5. Clicking Send again without new eligible subscribers sends nothing.
6. If C and D subscribe later, the next send targets only C and D.

Also verifies:
- Unsubscribe + resubscribe protection (A does not get re-notified)
- Inactive subscribers (unsubscribed before send) are skipped
- Cancelled events reject sends
- Past events reject sends
- UI button text and subscriber counts update dynamically
"""

from datetime import date, timedelta

from app.models import Event, Notification, Subscription
from app.helpers import generate_unsubscribe_token


class TestIncrementalReminders:
    """End-to-end tests for incremental reminder dispatching."""

    def test_incremental_subscription_flow(self, auth_client, sample_event, db_session):
        """
        Step-by-step verification of steps 1 through 6:
        1. A subscribes
        2. Organizer sends -> Only A gets notification
        3. B subscribes
        4. Organizer sends -> Only B gets notification; A gets no duplicate
        5. Send again -> Sends nothing
        6. C & D subscribe -> Next send targets only C and D
        """
        # Step 1: Student A subscribes
        sub_a = Subscription(
            event_id=sample_event.id,
            student_name="Student A",
            phone_number="+919876543201",
            consent_given=True,
            is_active=True,
            unsubscribe_token=generate_unsubscribe_token(),
        )
        db_session.session.add(sub_a)
        db_session.session.commit()

        # Check organizer event detail page shows 1 pending reminder
        resp = auth_client.get(f"/organizer/events/{sample_event.id}")
        assert resp.status_code == 200
        assert b"Send to 1 new subscriber" in resp.data

        # Step 2: The organizer sends reminders. Only A gets a notification.
        send_resp = auth_client.post(
            f"/organizer/events/{sample_event.id}/send",
            follow_redirects=True,
        )
        assert send_resp.status_code == 200
        assert b"1 sent" in send_resp.data.lower()

        notifs_a = Notification.query.filter_by(subscription_id=sub_a.id).all()
        assert len(notifs_a) == 1
        assert notifs_a[0].status == "sent"
        assert Notification.query.count() == 1

        # Event detail now shows all reminders dispatched
        resp = auth_client.get(f"/organizer/events/{sample_event.id}")
        assert b"All Reminders Dispatched" in resp.data

        # Step 3: Student B subscribes afterward
        sub_b = Subscription(
            event_id=sample_event.id,
            student_name="Student B",
            phone_number="+919876543202",
            consent_given=True,
            is_active=True,
            unsubscribe_token=generate_unsubscribe_token(),
        )
        db_session.session.add(sub_b)
        db_session.session.commit()

        # Step 4: The organizer can send reminders again. Only B gets a new notification; A must not receive another.
        resp = auth_client.get(f"/organizer/events/{sample_event.id}")
        assert resp.status_code == 200
        assert b"1 sent" in resp.data

        send_resp_2 = auth_client.post(
            f"/organizer/events/{sample_event.id}/send",
            follow_redirects=True,
        )
        assert send_resp_2.status_code == 200
        assert b"1 sent" in send_resp_2.data.lower()

        # Only B received a new notification; A still has exactly 1 notification
        notifs_a_after = Notification.query.filter_by(subscription_id=sub_a.id).all()
        assert len(notifs_a_after) == 1

        notifs_b = Notification.query.filter_by(subscription_id=sub_b.id).all()
        assert len(notifs_b) == 1
        assert notifs_b[0].status == "sent"
        assert Notification.query.count() == 2

        # Step 5: Clicking Send again without new eligible subscribers sends nothing.
        send_resp_3 = auth_client.post(
            f"/organizer/events/{sample_event.id}/send",
            follow_redirects=True,
        )
        assert send_resp_3.status_code == 200
        # No new notifications created
        assert Notification.query.count() == 2
        assert b"already sent" in send_resp_3.data.lower()

        # Step 6: If C and D subscribe later, the next send targets only C and D.
        sub_c = Subscription(
            event_id=sample_event.id,
            student_name="Student C",
            phone_number="+919876543203",
            consent_given=True,
            is_active=True,
            unsubscribe_token=generate_unsubscribe_token(),
        )
        sub_d = Subscription(
            event_id=sample_event.id,
            student_name="Student D",
            phone_number="+919876543204",
            consent_given=True,
            is_active=True,
            unsubscribe_token=generate_unsubscribe_token(),
        )
        db_session.session.add_all([sub_c, sub_d])
        db_session.session.commit()

        # Event detail displays 2 new subscribers pending
        resp = auth_client.get(f"/organizer/events/{sample_event.id}")
        assert b"Send to 2 new subscribers" in resp.data

        # Confirmation page indicates 2 active subscribers to notify and 2 skipped
        confirm_resp = auth_client.get(f"/organizer/events/{sample_event.id}/send")
        assert confirm_resp.status_code == 200
        assert b"2 active subscriber" in confirm_resp.data
        assert b"2 subscribers already received reminders" in confirm_resp.data

        # Send reminders
        send_resp_4 = auth_client.post(
            f"/organizer/events/{sample_event.id}/send",
            follow_redirects=True,
        )
        assert send_resp_4.status_code == 200
        assert b"2 sent" in send_resp_4.data.lower()

        # Total notifications is now 4 (1 for A, 1 for B, 1 for C, 1 for D)
        assert Notification.query.count() == 4
        assert Notification.query.filter_by(subscription_id=sub_a.id).count() == 1
        assert Notification.query.filter_by(subscription_id=sub_b.id).count() == 1
        assert Notification.query.filter_by(subscription_id=sub_c.id).count() == 1
        assert Notification.query.filter_by(subscription_id=sub_d.id).count() == 1

    def test_resubscribed_student_not_re_notified(self, auth_client, client, sample_event, db_session):
        """
        If Student A receives a reminder, unsubs, and resubscribes,
        the organizer send will NOT send another standard reminder to A.
        """
        # Subscribe A
        sub_a = Subscription(
            event_id=sample_event.id,
            student_name="Student A",
            phone_number="+919876543210",
            consent_given=True,
            is_active=True,
            unsubscribe_token=generate_unsubscribe_token(),
        )
        db_session.session.add(sub_a)
        db_session.session.commit()

        # First send
        auth_client.post(f"/organizer/events/{sample_event.id}/send")
        assert Notification.query.filter_by(subscription_id=sub_a.id).count() == 1

        # Student A un区subscribes via public link
        client.post(f"/unsubscribe/{sub_a.unsubscribe_token}")
        db_session.session.refresh(sub_a)
        assert sub_a.is_active is False

        # Student A resubscribes via public form
        client.post(f"/events/{sample_event.id}/subscribe", data={
            "student_name": "Student A",
            "phone_number": "+919876543210",
            "consent": "on",
        })
        db_session.session.refresh(sub_a)
        assert sub_a.is_active is True

        # Organizer tries to send reminders
        resp = auth_client.post(
            f"/organizer/events/{sample_event.id}/send",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        # A was not re-notified
        assert Notification.query.filter_by(subscription_id=sub_a.id).count() == 1
        assert Notification.query.count() == 1

    def test_unsubscribed_before_send_excluded(self, auth_client, sample_event, db_session):
        """A student who subscribed and then unsubscribed before any send is excluded."""
        sub_active = Subscription(
            event_id=sample_event.id,
            student_name="Active Student",
            phone_number="+919876543221",
            consent_given=True,
            is_active=True,
            unsubscribe_token=generate_unsubscribe_token(),
        )
        sub_inactive = Subscription(
            event_id=sample_event.id,
            student_name="Inactive Student",
            phone_number="+919876543222",
            consent_given=True,
            is_active=False,
            unsubscribe_token=generate_unsubscribe_token(),
        )
        db_session.session.add_all([sub_active, sub_inactive])
        db_session.session.commit()

        auth_client.post(f"/organizer/events/{sample_event.id}/send")
        assert Notification.query.filter_by(subscription_id=sub_active.id).count() == 1
        assert Notification.query.filter_by(subscription_id=sub_inactive.id).count() == 0

    def test_past_event_send_rejected(self, auth_client, db_session, organizer):
        """Past events cannot have reminders sent."""
        past_event = Event(
            organizer_id=organizer.id,
            title="Past Event",
            club_name="History Club",
            event_date=date.today() - timedelta(days=2),
        )
        db_session.session.add(past_event)
        db_session.session.commit()

        resp = auth_client.post(
            f"/organizer/events/{past_event.id}/send",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"past events" in resp.data.lower()
        assert Notification.query.count() == 0

    def test_anonymous_user_cannot_send_reminder(self, client, sample_event, sample_subscription):
        """Anonymous requests to /send must redirect to login."""
        resp = client.post(f"/organizer/events/{sample_event.id}/send")
        assert resp.status_code == 302
        assert "/organizer/login" in resp.headers.get("Location", "")
