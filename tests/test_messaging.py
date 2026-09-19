"""
Tests for the messaging service layer.

Covers:
- Demo mode: success simulation, failure simulation
- Factory function: selects correct service based on config
- Message building
"""

from app.messaging import DemoMessagingService, get_messaging_service
from app.helpers import build_reminder_message, mask_phone
from app.models import Event

from datetime import date, time


class TestDemoMessagingService:
    """Verify demo mode behavior."""

    def test_success_simulation(self):
        """Normal numbers should simulate success."""
        svc = DemoMessagingService()
        result = svc.send_sms(to="+919876543210", body="Test message")
        assert result["success"] is True
        assert result["provider_message_id"] is not None
        assert result["provider_message_id"].startswith("DEMO_")
        assert result["error"] is None

    def test_failure_simulation(self):
        """Numbers ending in 0000 should simulate failure."""
        svc = DemoMessagingService()
        result = svc.send_sms(to="+911234560000", body="Test message")
        assert result["success"] is False
        assert result["provider_message_id"] is None
        assert result["error"] is not None
        assert "simulated" in result["error"].lower()

    def test_different_numbers_get_different_ids(self):
        """Each call should generate a unique provider message ID."""
        svc = DemoMessagingService()
        r1 = svc.send_sms(to="+919876543210", body="Msg 1")
        r2 = svc.send_sms(to="+919876543211", body="Msg 2")
        assert r1["provider_message_id"] != r2["provider_message_id"]


class TestMessagingFactory:
    """Verify the get_messaging_service factory function."""

    def test_demo_mode_returns_demo_service(self, app):
        """Demo config should return DemoMessagingService."""
        with app.app_context():
            svc = get_messaging_service()
            assert isinstance(svc, DemoMessagingService)

    def test_twilio_mode_without_credentials_raises_error(self, app):
        """Twilio mode without credentials must raise a clear configuration error."""
        import pytest
        app.config["MESSAGING_MODE"] = "twilio"
        app.config["TWILIO_ACCOUNT_SID"] = ""
        try:
            with app.app_context():
                with pytest.raises(ValueError, match="required Twilio credentials"):
                    get_messaging_service()
        finally:
            app.config["MESSAGING_MODE"] = "demo"


class TestHelpers:
    """Verify helper functions."""

    def test_mask_phone_standard(self):
        """Standard phone should be masked."""
        assert mask_phone("+919876543210") == "+91******3210"

    def test_mask_phone_short(self):
        """Short phone should show ****."""
        assert mask_phone("+123") == "****"

    def test_mask_phone_empty(self):
        """Empty phone should show ****."""
        assert mask_phone("") == "****"

    def test_build_reminder_message(self, app, sample_event):
        """Reminder message should contain event details."""
        with app.app_context():
            msg = build_reminder_message(sample_event)
            assert "Test Workshop" in msg
            assert "Test Club" in msg
            assert "Room 101" in msg
