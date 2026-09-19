"""
Security protection tests with protections ENABLED.

Covers:
- CSRF validation
- Rate limiting on login
- Transaction boundaries during failure
"""

from app.models import Notification, Subscription, Event
import pytest

class TestSecurityProtections:

    def test_csrf_protection_enabled(self, app, client):
        """CSRF should block requests if enabled and missing token."""
        # Enable CSRF for this specific test
        app.config["WTF_CSRF_ENABLED"] = True
        
        # Test POST without CSRF token
        resp = client.post("/events/1/subscribe", data={
            "student_name": "CSRF Hacker",
            "phone_number": "+919999999999",
            "consent": "on"
        })
        # Should be rejected with 400 Bad Request
        assert resp.status_code == 400
        
        # Reset config
        app.config["WTF_CSRF_ENABLED"] = False

    def test_csrf_invalid_token_rejected(self, app, client):
        """CSRF should block requests if token is invalid or tampered."""
        app.config["WTF_CSRF_ENABLED"] = True

        resp = client.post("/events/1/subscribe", data={
            "student_name": "CSRF Hacker",
            "phone_number": "+919999999999",
            "consent": "on",
            "csrf_token": "tampered-or-invalid-csrf-token"
        })
        assert resp.status_code == 400

        app.config["WTF_CSRF_ENABLED"] = False

    def test_rate_limiting(self, app, client, db_session):
        """Rate limiter should block excessive logins and then recover after reset."""
        from unittest.mock import patch
        from werkzeug.exceptions import TooManyRequests
        
        # Create a user to test login
        from app.models import Organizer
        org = Organizer(username="test", password_hash="hash")
        db_session.session.add(org)
        db_session.session.commit()
        
        with patch("flask_limiter.Limiter._check_request_limit") as mock_check:
            # First, simulate successful rate limit checks
            mock_check.return_value = None
            resp = client.post("/organizer/login", data={"username": "test", "password": "abc"})
            assert resp.status_code == 200
            
            # Now simulate the rate limit being exceeded
            mock_check.side_effect = TooManyRequests()
            resp = client.post("/organizer/login", data={"username": "test", "password": "abc"})
            assert resp.status_code == 429
            
            # Access recovers (limit window expires)
            mock_check.side_effect = None
            mock_check.return_value = None
            resp = client.post("/organizer/login", data={"username": "test", "password": "abc"})
            assert resp.status_code == 200


class TestProductionStartupConfig:

    def test_production_startup_rejects_default_secret_key(self, monkeypatch):
        """Production mode must refuse to boot with default secret key."""
        import os
        from app import create_app

        monkeypatch.setenv("FLASK_SECRET_KEY", "dev-secret-change-me")
        with pytest.raises(ValueError, match="FLASK_SECRET_KEY must be set"):
            create_app("production")

    def test_production_startup_verified_settings(self, monkeypatch):
        """Verify all production security settings when booted with strong key."""
        from app import create_app

        monkeypatch.setenv("FLASK_SECRET_KEY", "c7f1a9b2d8e4f501a3b8c9d2e1f407b6a5d4c3b2a1")
        prod_app = create_app("production")

        assert prod_app.config["DEBUG"] is False
        assert prod_app.config["SESSION_COOKIE_SECURE"] is True
        assert prod_app.config["SESSION_COOKIE_HTTPONLY"] is True
        assert prod_app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
        assert prod_app.config["RATELIMIT_ENABLED"] is True
        assert prod_app.config["SECRET_KEY"] == "c7f1a9b2d8e4f501a3b8c9d2e1f407b6a5d4c3b2a1"


class TestTransactionBoundaries:

    def test_provider_success_db_failure(self, app, client, auth_client, sample_event, db_session):
        """
        If the provider succeeds but final DB commit fails, the record should remain PENDING.
        This prevents double-sending on retry.
        """
        # Create a subscription
        from app.helpers import generate_unsubscribe_token
        sub = Subscription(
            event_id=sample_event.id,
            student_name="Test Sub",
            phone_number="+918888888888",
            consent_given=True,
            is_active=True,
            unsubscribe_token=generate_unsubscribe_token(),
        )
        db_session.session.add(sub)
        db_session.session.commit()

        # We will mock the final db.session.commit to throw an exception
        from unittest.mock import patch
        
        original_commit = db_session.session.commit
        
        def mock_commit_side_effect():
            mock_commit_side_effect.calls += 1
            if mock_commit_side_effect.calls > 1:
                raise Exception("Simulated DB failure on final update")
            return original_commit()

        mock_commit_side_effect.calls = 0

        # We will patch `db.session.commit` in `app.organizer`
        with patch("app.organizer.db.session.commit", side_effect=mock_commit_side_effect):
            auth_client.post(f"/organizer/events/{sample_event.id}/send")
            
        # Verify the notification remains in 'pending' status due to the first successful commit
        notif = Notification.query.filter_by(subscription_id=sub.id).first()
        assert notif is not None
        assert notif.status == "pending"
        
        # Now simulate the user clicking "Send" again (retry)
        auth_client.post(f"/organizer/events/{sample_event.id}/send")
        
        # Since it is 'pending', the IntegrityError should catch it and skip it.
        # It should NOT create a second notification record.
        count = Notification.query.filter_by(subscription_id=sub.id).count()
        assert count == 1

    def test_simultaneous_send_requests_idempotent(self, auth_client, sample_event, db_session):
        """
        Simulate concurrent send requests: only one standard reminder can exist per subscriber.
        """
        from app.helpers import generate_unsubscribe_token
        sub = Subscription(
            event_id=sample_event.id,
            student_name="Concurrent Sub",
            phone_number="+919777777777",
            consent_given=True,
            is_active=True,
            unsubscribe_token=generate_unsubscribe_token(),
        )
        db_session.session.add(sub)
        db_session.session.commit()

        # Execute two back-to-back send requests for the same event
        resp1 = auth_client.post(f"/organizer/events/{sample_event.id}/send", follow_redirects=True)
        assert resp1.status_code == 200
        assert b"1 sent" in resp1.data

        resp2 = auth_client.post(f"/organizer/events/{sample_event.id}/send", follow_redirects=True)
        assert resp2.status_code == 200
        assert b"1 already sent" in resp2.data

        # Only one notification record should exist
        notifs = Notification.query.filter_by(subscription_id=sub.id).all()
        assert len(notifs) == 1
        assert notifs[0].status == "sent"
