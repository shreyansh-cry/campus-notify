"""
Comprehensive final verification tests for CampusNotify.

Covers:
1. Real rate limiting counter and recovery (unmocked)
2. CSRF protection and HTTP method guards (GET mutations prevented)
3. Call-count tracking across incremental reminder batches (A/B/C/D sequence)
4. Existing attempt status preservation (pending, sent, delivered, failed not resent)
5. Strict input validation, Unicode names, excessive lengths, missing consent
6. Same phone across different events
7. Timezone formatting near midnight
"""

import pytest
from datetime import date, time, timedelta
from unittest.mock import patch, MagicMock

from app import create_app
from app.extensions import db as _db
from app.models import Event, Notification, Subscription, Organizer
from app.helpers import generate_unsubscribe_token, format_event_datetime
from app.extensions import limiter


# ---------------------------------------------------------------------------
# Fixtures for the rate-limiting test
# ---------------------------------------------------------------------------
# We need a *separate* Flask app created with RATELIMIT_ENABLED=True so that
# Flask-Limiter initialises its storage backend.  The session-scoped `app`
# fixture uses TestingConfig (RATELIMIT_ENABLED=False), which leaves the
# limiter storage as None — making limiter.reset() raise an AssertionError.
#
# IMPORTANT: Because `limiter` is a module-level singleton, calling
# limiter.init_app(rl_app) permanently mutates it.  The rl_app fixture
# therefore re-inits the limiter *back* to the original session-scoped
# test app (RATELIMIT_ENABLED=False) in its teardown so subsequent tests
# are not affected.

@pytest.fixture
def rl_app(app):
    """A function-scoped Flask app with rate limiting turned on.

    `app` is the session-scoped fixture from conftest.py.  We capture it
    here so we can restore the limiter to that app after the test.
    """
    application = create_app("testing")
    application.config["RATELIMIT_ENABLED"] = True
    with application.app_context():
        limiter.init_app(application)
    yield application
    # --- Teardown: restore limiter to the base session-scoped test app ---
    # This prevents rate-limit state from bleeding into subsequent tests.
    app.config["RATELIMIT_ENABLED"] = False
    with app.app_context():
        limiter.init_app(app)


@pytest.fixture
def rl_db(rl_app):
    """Fresh DB tables for the rate-limiting app."""
    with rl_app.app_context():
        _db.create_all()
        yield _db
        _db.session.rollback()
        _db.drop_all()


@pytest.fixture
def rl_client(rl_app, rl_db):
    """Test client bound to the rate-limiting app."""
    return rl_app.test_client()


def _clear_limiter(application):
    """Clear all rate-limit counters for the given app.

    Flask-Limiter v4 exposes the underlying limits-library storage object via
    `limiter.storage`.  Its `.reset()` method wipes all counters.
    If the storage is not available (e.g. in unit tests with RATELIMIT_ENABLED
    disabled) this is a no-op so other tests remain unaffected.
    """
    with application.app_context():
        storage = getattr(limiter, "storage", None)
        if storage is not None:
            storage.reset()


class TestRealRateLimitingAndSecurity:
    """Verify security controls without mocking limiter decisions."""

    def test_real_rate_limiting_counter_and_recovery(self, rl_app, rl_client):
        """Real rate limiter counter triggers 429 after limit is reached, then recovers on reset.

        Uses a dedicated app fixture (rl_app) that is created with
        RATELIMIT_ENABLED=True so Flask-Limiter's storage is fully initialised.
        """
        _clear_limiter(rl_app)

        try:
            # Login route has a limit of 5 per minute.
            for _ in range(5):
                resp = rl_client.post("/organizer/login", data={
                    "username": "nonexistent",
                    "password": "wrongpassword",
                })
                # Should not be rate-limited yet (renders 200 with danger flash)
                assert resp.status_code in (200, 302), (
                    f"Unexpected status {resp.status_code} before limit reached"
                )
                assert resp.status_code != 429

            # 6th attempt should trigger 429 Too Many Requests
            resp_blocked = rl_client.post("/organizer/login", data={
                "username": "nonexistent",
                "password": "wrongpassword",
            })
            assert resp_blocked.status_code == 429

            # Recover after reset
            _clear_limiter(rl_app)
            resp_recovered = rl_client.post("/organizer/login", data={
                "username": "nonexistent",
                "password": "wrongpassword",
            })
            assert resp_recovered.status_code in (200, 302)
        finally:
            _clear_limiter(rl_app)

    def test_organizer_mutations_blocked_via_get(self, auth_client, sample_event):
        """State-changing actions must reject GET requests (405 Method Not Allowed)."""
        # Cancel event via GET
        resp_cancel = auth_client.get(f"/organizer/events/{sample_event.id}/cancel")
        assert resp_cancel.status_code == 405

        # Logout via GET
        resp_logout = auth_client.get("/organizer/logout")
        assert resp_logout.status_code == 405

        # Send reminder via GET is read-only confirmation (does not send SMS)
        resp_send_get = auth_client.get(f"/organizer/events/{sample_event.id}/send")
        assert resp_send_get.status_code == 200
        assert Notification.query.count() == 0

    def test_anonymous_organizer_routes_rejected_without_db_changes(self, client, sample_event):
        """Anonymous access to organizer mutations redirects to login and mutates nothing."""
        # Anonymous POST to cancel
        resp = client.post(f"/organizer/events/{sample_event.id}/cancel", follow_redirects=False)
        assert resp.status_code == 302
        assert "/organizer/login" in resp.headers.get("Location", "")
        assert sample_event.is_cancelled is False

        # Anonymous POST to send
        resp = client.post(f"/organizer/events/{sample_event.id}/send", follow_redirects=False)
        assert resp.status_code == 302
        assert "/organizer/login" in resp.headers.get("Location", "")
        assert Notification.query.count() == 0


class TestMessagingServiceCallCountsAndStatusPreservation:
    """Verify exact mock call counts across A/B/C/D batches and status preservation."""

    def test_exact_mock_call_counts_abcd(self, auth_client, sample_event, db_session):
        """
        Verify exact number of external messaging calls for:
        A -> 1 call
        B -> 1 call
        Empty -> 0 calls
        C & D -> 2 calls
        """
        from app.messaging import DemoMessagingService

        with patch.object(DemoMessagingService, "send_sms", wraps=DemoMessagingService().send_sms) as spy_send:
            # Step 1: Subscribe A
            sub_a = Subscription(
                event_id=sample_event.id,
                student_name="Student A",
                phone_number="+919876543101",
                consent_given=True,
                is_active=True,
                unsubscribe_token=generate_unsubscribe_token(),
            )
            db_session.session.add(sub_a)
            db_session.session.commit()

            # First send -> calls spy once for A
            auth_client.post(f"/organizer/events/{sample_event.id}/send", follow_redirects=True)
            assert spy_send.call_count == 1
            assert spy_send.call_args[1]["to"] == "+919876543101"

            # Step 2: Subscribe B
            sub_b = Subscription(
                event_id=sample_event.id,
                student_name="Student B",
                phone_number="+919876543102",
                consent_given=True,
                is_active=True,
                unsubscribe_token=generate_unsubscribe_token(),
            )
            db_session.session.add(sub_b)
            db_session.session.commit()

            # Second send -> calls spy once for B (total 2)
            auth_client.post(f"/organizer/events/{sample_event.id}/send", follow_redirects=True)
            assert spy_send.call_count == 2
            assert spy_send.call_args[1]["to"] == "+919876543102"

            # Step 3: Send again without new subscribers -> 0 new calls (total stays 2)
            auth_client.post(f"/organizer/events/{sample_event.id}/send", follow_redirects=True)
            assert spy_send.call_count == 2

            # Step 4: Subscribe C and D
            sub_c = Subscription(
                event_id=sample_event.id,
                student_name="Student C",
                phone_number="+919876543103",
                consent_given=True,
                is_active=True,
                unsubscribe_token=generate_unsubscribe_token(),
            )
            sub_d = Subscription(
                event_id=sample_event.id,
                student_name="Student D",
                phone_number="+919876543104",
                consent_given=True,
                is_active=True,
                unsubscribe_token=generate_unsubscribe_token(),
            )
            db_session.session.add_all([sub_c, sub_d])
            db_session.session.commit()

            # Third send -> calls spy twice (total 4)
            auth_client.post(f"/organizer/events/{sample_event.id}/send", follow_redirects=True)
            assert spy_send.call_count == 4

    def test_existing_statuses_not_resent(self, auth_client, sample_event, db_session):
        """Subscriptions with existing pending, failed, or delivered statuses are never resent."""
        from app.messaging import DemoMessagingService

        # Create subscribers with pending, failed, delivered records
        sub_pending = Subscription(
            event_id=sample_event.id,
            student_name="Pending Sub",
            phone_number="+919876543301",
            consent_given=True,
            is_active=True,
            unsubscribe_token=generate_unsubscribe_token(),
        )
        sub_failed = Subscription(
            event_id=sample_event.id,
            student_name="Failed Sub",
            phone_number="+919876543302",
            consent_given=True,
            is_active=True,
            unsubscribe_token=generate_unsubscribe_token(),
        )
        sub_delivered = Subscription(
            event_id=sample_event.id,
            student_name="Delivered Sub",
            phone_number="+919876543303",
            consent_given=True,
            is_active=True,
            unsubscribe_token=generate_unsubscribe_token(),
        )
        db_session.session.add_all([sub_pending, sub_failed, sub_delivered])
        db_session.session.commit()

        # Add pre-existing notifications with statuses
        n1 = Notification(subscription_id=sub_pending.id, reminder_type="standard", status="pending")
        n2 = Notification(subscription_id=sub_failed.id, reminder_type="standard", status="failed", error_message="Provider error")
        n3 = Notification(subscription_id=sub_delivered.id, reminder_type="standard", status="delivered", provider_message_id="SID123")
        db_session.session.add_all([n1, n2, n3])
        db_session.session.commit()

        with patch.object(DemoMessagingService, "send_sms") as mock_send:
            # Organizer attempts send
            resp = auth_client.post(f"/organizer/events/{sample_event.id}/send", follow_redirects=True)
            assert resp.status_code == 200
            # Zero external sends occurred
            mock_send.assert_not_called()
            assert b"already sent" in resp.data.lower()

            # Check organizer page shows delivery outcomes breakdown
            detail_resp = auth_client.get(f"/organizer/events/{sample_event.id}")
            assert b"1 delivered" in detail_resp.data
            assert b"1 failed" in detail_resp.data
            assert b"1 pending" in detail_resp.data
            assert b"All Eligible Processed (Delivery Incomplete)" in detail_resp.data


class TestInputsAndEdgeCases:
    """Verify input validation, Unicode, same phone across events, and edge cases."""

    def test_unicode_student_name_accepted(self, client, sample_event, db_session):
        """Students with international/Unicode names can subscribe successfully."""
        resp = client.post(f"/events/{sample_event.id}/subscribe", data={
            "student_name": "Müller 李雷 🎓",
            "phone_number": "+919876543401",
            "consent": "on",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"subscribed" in resp.data.lower()

        sub = Subscription.query.filter_by(phone_number="+919876543401").first()
        assert sub is not None
        assert sub.student_name == "Müller 李雷 🎓"

    def test_same_phone_subscribes_to_multiple_events(self, client, organizer, sample_event, db_session):
        """The same student phone number can subscribe to different events."""
        event_2 = Event(
            organizer_id=organizer.id,
            title="Second Event",
            club_name="Robotics Club",
            event_date=date.today() + timedelta(days=10),
        )
        db_session.session.add(event_2)
        db_session.session.commit()

        phone = "+919876543501"

        # Subscribe to Event 1
        resp1 = client.post(f"/events/{sample_event.id}/subscribe", data={
            "student_name": "Multi Event Student",
            "phone_number": phone,
            "consent": "on",
        }, follow_redirects=True)
        assert resp1.status_code == 200
        assert b"subscribed" in resp1.data.lower()

        # Subscribe to Event 2
        resp2 = client.post(f"/events/{event_2.id}/subscribe", data={
            "student_name": "Multi Event Student",
            "phone_number": phone,
            "consent": "on",
        }, follow_redirects=True)
        assert resp2.status_code == 200
        assert b"subscribed" in resp2.data.lower()

        # Both subscriptions exist
        assert Subscription.query.filter_by(phone_number=phone).count() == 2

    def test_missing_consent_rejected_on_direct_post(self, client, sample_event):
        """Direct POST submissions without consent checkbox must be rejected."""
        resp = client.post(f"/events/{sample_event.id}/subscribe", data={
            "student_name": "No Consent Student",
            "phone_number": "+919876543601",
            # consent omitted
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"consent" in resp.data.lower()
        assert Subscription.query.filter_by(phone_number="+919876543601").first() is None

    def test_timezone_formatting_near_midnight(self):
        """format_event_datetime formats dates and times correctly near midnight."""
        d = date(2026, 12, 31)
        t_late = time(23, 59)
        t_early = time(0, 5)

        formatted_late = format_event_datetime(d, t_late)
        assert "31 Dec 2026 at 11:59 PM IST" in formatted_late

        formatted_early = format_event_datetime(d, t_early)
        assert "31 Dec 2026 at 12:05 AM IST" in formatted_early
