"""
Tests for the Twilio delivery-status webhook.

Covers:
- Valid webhook updates notification status
- Invalid signatures are rejected
- Status progression (don't overwrite final statuses)
- Repeated callbacks are handled safely
- Unknown message SIDs are handled gracefully
"""

from unittest.mock import patch

from app.models import Notification, Subscription
from app.helpers import generate_unsubscribe_token


def _create_notification(db_session, sample_event, status="sent", provider_message_id="SM_test_123"):
    """Helper: create a subscription + notification for webhook tests."""
    sub = Subscription(
        event_id=sample_event.id,
        student_name="Webhook Test",
        phone_number="+919999999999",
        consent_given=True,
        is_active=True,
        unsubscribe_token=generate_unsubscribe_token(),
    )
    db_session.session.add(sub)
    db_session.session.flush()

    notif = Notification(
        subscription_id=sub.id,
        reminder_type="standard",
        status=status,
        provider_message_id=provider_message_id,
    )
    db_session.session.add(notif)
    db_session.session.commit()
    return notif


class TestWebhookStatusUpdate:
    """Verify delivery status updates via webhook."""

    def test_delivered_status_update(self, client, sample_event, db_session):
        """Webhook should update status from 'sent' to 'delivered'."""
        notif = _create_notification(db_session, sample_event)

        resp = client.post("/webhooks/twilio/status", data={
            "MessageSid": "SM_test_123",
            "MessageStatus": "delivered",
        })
        assert resp.status_code == 200

        db_session.session.refresh(notif)
        assert notif.status == "delivered"

    def test_failed_status_update(self, client, sample_event, db_session):
        """Webhook should update status from 'sent' to 'failed'."""
        notif = _create_notification(db_session, sample_event)

        resp = client.post("/webhooks/twilio/status", data={
            "MessageSid": "SM_test_123",
            "MessageStatus": "failed",
        })
        assert resp.status_code == 200

        db_session.session.refresh(notif)
        assert notif.status == "failed"

    def test_status_progression_prevents_overwrite(self, client, sample_event, db_session):
        """Once 'delivered', a later 'sent' should not overwrite."""
        notif = _create_notification(db_session, sample_event, status="delivered")

        resp = client.post("/webhooks/twilio/status", data={
            "MessageSid": "SM_test_123",
            "MessageStatus": "sent",
        })
        assert resp.status_code == 200

        db_session.session.refresh(notif)
        assert notif.status == "delivered"  # Should NOT have changed

    def test_failed_not_overwritten_by_sent(self, client, sample_event, db_session):
        """Once 'failed', it should not be overwritten by 'sent'."""
        notif = _create_notification(db_session, sample_event, status="failed")

        resp = client.post("/webhooks/twilio/status", data={
            "MessageSid": "SM_test_123",
            "MessageStatus": "sent",
        })
        assert resp.status_code == 200

        db_session.session.refresh(notif)
        assert notif.status == "failed"  # Should NOT have changed

    def test_repeated_delivered_callback(self, client, sample_event, db_session):
        """Repeated 'delivered' callbacks should be handled safely."""
        notif = _create_notification(db_session, sample_event)

        # First callback
        client.post("/webhooks/twilio/status", data={
            "MessageSid": "SM_test_123",
            "MessageStatus": "delivered",
        })

        # Second callback — same status
        resp = client.post("/webhooks/twilio/status", data={
            "MessageSid": "SM_test_123",
            "MessageStatus": "delivered",
        })
        assert resp.status_code == 200

        db_session.session.refresh(notif)
        assert notif.status == "delivered"

    def test_unknown_message_sid(self, client):
        """Webhook for an unknown SID should return 200 (don't retry)."""
        resp = client.post("/webhooks/twilio/status", data={
            "MessageSid": "SM_unknown_12345",
            "MessageStatus": "delivered",
        })
        assert resp.status_code == 200

    def test_missing_fields(self, client):
        """Webhook with missing fields should return 200 gracefully."""
        resp = client.post("/webhooks/twilio/status", data={})
        assert resp.status_code == 200


class TestWebhookSignatureValidation:
    """Verify Twilio signature validation in Twilio mode."""

    def test_invalid_signature_rejected_in_twilio_mode(self, app, client, sample_event, db_session):
        """In Twilio mode, invalid signatures should be rejected with 403."""
        notif = _create_notification(db_session, sample_event)

        # Temporarily switch to Twilio mode
        app.config["MESSAGING_MODE"] = "twilio"
        app.config["TWILIO_AUTH_TOKEN"] = "fake_auth_token_for_testing"

        try:
            # Mock the validator to return False (invalid signature)
            with patch("app.webhooks.validate_twilio_signature", return_value=False):
                resp = client.post("/webhooks/twilio/status", data={
                    "MessageSid": "SM_test_123",
                    "MessageStatus": "delivered",
                })
                assert resp.status_code == 403
        finally:
            # Restore demo mode
            app.config["MESSAGING_MODE"] = "demo"
            app.config["TWILIO_AUTH_TOKEN"] = ""

    def test_valid_signature_accepted_in_twilio_mode(self, app, client, sample_event, db_session):
        """In Twilio mode, valid signatures should be accepted."""
        notif = _create_notification(db_session, sample_event)

        app.config["MESSAGING_MODE"] = "twilio"
        app.config["TWILIO_AUTH_TOKEN"] = "fake_auth_token_for_testing"

        try:
            with patch("app.webhooks.validate_twilio_signature", return_value=True):
                resp = client.post("/webhooks/twilio/status", data={
                    "MessageSid": "SM_test_123",
                    "MessageStatus": "delivered",
                })
                assert resp.status_code == 200

                db_session.session.refresh(notif)
                assert notif.status == "delivered"
        finally:
            app.config["MESSAGING_MODE"] = "demo"
            app.config["TWILIO_AUTH_TOKEN"] = ""
