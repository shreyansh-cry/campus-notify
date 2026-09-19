"""
Tests for student-facing features.

Covers:
- Browsing events
- Subscribing with valid data
- Server-side validation (name, phone, consent)
- Duplicate subscription prevention
- Unsubscribe flow
"""

from app.models import Subscription


class TestBrowseEvents:
    """Verify the public event listing page."""

    def test_events_page_renders(self, client):
        """Home page should render even with no events."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Upcoming Campus Events" in resp.data

    def test_events_page_shows_events(self, client, sample_event):
        """Home page should display the sample event."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Test Workshop" in resp.data
        assert b"Test Club" in resp.data

    def test_event_detail_page(self, client, sample_event):
        """Event detail page should show full event info and subscribe form."""
        resp = client.get(f"/events/{sample_event.id}")
        assert resp.status_code == 200
        assert b"Test Workshop" in resp.data
        assert b"Subscribe for Reminder" in resp.data

    def test_cancelled_event_shows_notice(self, client, cancelled_event):
        """Cancelled event should show a notice."""
        resp = client.get(f"/events/{cancelled_event.id}")
        assert resp.status_code == 200
        assert b"cancelled" in resp.data.lower()

    def test_nonexistent_event_404(self, client):
        """Requesting a non-existent event should return 404."""
        resp = client.get("/events/99999")
        assert resp.status_code == 404


class TestSubscribe:
    """Verify subscription creation and validation."""

    def test_successful_subscription(self, client, sample_event):
        """Valid data should create a subscription."""
        resp = client.post(f"/events/{sample_event.id}/subscribe", data={
            "student_name": "New Student",
            "phone_number": "+919876543210",
            "consent": "on",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"subscribed" in resp.data.lower()

        # Verify in database
        sub = Subscription.query.filter_by(
            event_id=sample_event.id, phone_number="+919876543210"
        ).first()
        assert sub is not None
        assert sub.is_active is True
        assert sub.consent_given is True

    def test_missing_name(self, client, sample_event):
        """Empty name should be rejected."""
        resp = client.post(f"/events/{sample_event.id}/subscribe", data={
            "student_name": "",
            "phone_number": "+919876543210",
            "consent": "on",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Name must be" in resp.data

    def test_short_name(self, client, sample_event):
        """Name shorter than 2 characters should be rejected."""
        resp = client.post(f"/events/{sample_event.id}/subscribe", data={
            "student_name": "A",
            "phone_number": "+919876543210",
            "consent": "on",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Name must be" in resp.data

    def test_missing_phone(self, client, sample_event):
        """Empty phone should be rejected."""
        resp = client.post(f"/events/{sample_event.id}/subscribe", data={
            "student_name": "Test Student",
            "phone_number": "",
            "consent": "on",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Phone number is required" in resp.data

    def test_invalid_phone_format(self, client, sample_event):
        """Phone without + prefix should be rejected."""
        resp = client.post(f"/events/{sample_event.id}/subscribe", data={
            "student_name": "Test Student",
            "phone_number": "9876543210",
            "consent": "on",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"must start with +" in resp.data

    def test_phone_with_letters(self, client, sample_event):
        """Phone with non-digit characters should be rejected."""
        resp = client.post(f"/events/{sample_event.id}/subscribe", data={
            "student_name": "Test Student",
            "phone_number": "+91abcdefghij",
            "consent": "on",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"must start with +" in resp.data

    def test_missing_consent(self, client, sample_event):
        """Missing consent checkbox should be rejected."""
        resp = client.post(f"/events/{sample_event.id}/subscribe", data={
            "student_name": "Test Student",
            "phone_number": "+919876543210",
            # consent NOT included
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"consent" in resp.data.lower()

    def test_duplicate_subscription(self, client, sample_event, sample_subscription):
        """Same phone + same event should show friendly message, not crash."""
        resp = client.post(f"/events/{sample_event.id}/subscribe", data={
            "student_name": "Another Name",
            "phone_number": "+919876543210",
            "consent": "on",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"already subscribed" in resp.data.lower()

    def test_subscribe_to_cancelled_event(self, client, cancelled_event):
        """Subscribing to a cancelled event should show a warning."""
        resp = client.post(f"/events/{cancelled_event.id}/subscribe", data={
            "student_name": "Test Student",
            "phone_number": "+919876543210",
            "consent": "on",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"cancelled" in resp.data.lower()


class TestUnsubscribe:
    """Verify the unsubscribe flow."""

    def test_unsubscribe_page_renders(self, client, sample_subscription):
        """Unsubscribe page should render for a valid token."""
        resp = client.get(f"/unsubscribe/{sample_subscription.unsubscribe_token}")
        assert resp.status_code == 200
        assert b"Unsubscribe" in resp.data

    def test_successful_unsubscribe(self, client, sample_subscription, db_session):
        """POST should deactivate the subscription."""
        token = sample_subscription.unsubscribe_token
        resp = client.post(f"/unsubscribe/{token}", follow_redirects=True)
        assert resp.status_code == 200
        assert b"unsubscribed" in resp.data.lower()

        # Verify in database
        db_session.session.refresh(sample_subscription)
        assert sample_subscription.is_active is False
        assert sample_subscription.unsubscribed_at is not None

    def test_invalid_token_404(self, client):
        """Non-existent token should return 404."""
        resp = client.get("/unsubscribe/invalid-token-12345")
        assert resp.status_code == 404

    def test_resubscribe_after_unsubscribe(self, client, sample_event, sample_subscription, db_session):
        """Unsubscribed student re-subscribing should re-activate."""
        # First unsubscribe
        token = sample_subscription.unsubscribe_token
        client.post(f"/unsubscribe/{token}")

        # Now re-subscribe with same phone
        resp = client.post(f"/events/{sample_event.id}/subscribe", data={
            "student_name": "Test Student",
            "phone_number": "+919876543210",
            "consent": "on",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"re-activated" in resp.data.lower()

        db_session.session.refresh(sample_subscription)
        assert sample_subscription.is_active is True
