"""
Messaging service — the layer between the app and SMS delivery.

Two modes:
  1. DemoMessagingService (default): simulates sending. No real SMS.
     - Numbers ending in '0000' simulate a failure, everything else succeeds.
     - Clearly labels all output as simulated.

  2. TwilioMessagingService: sends real SMS through the Twilio REST API.
     - Only activated when MESSAGING_MODE=twilio and credentials are set.
     - Returns the Twilio Message SID as provider_message_id.
     - Catches TwilioRestException and returns a structured error.

Both return a dict:  {"success": bool, "provider_message_id": str|None, "error": str|None}
"""

import logging
import uuid

logger = logging.getLogger(__name__)


class DemoMessagingService:
    """
    Simulates SMS sending for demo and development.

    Convention for demo testing:
      - Phone numbers ending in '0000' will simulate a FAILURE.
      - All other numbers simulate SUCCESS.
    This lets you demonstrate both outcomes without any external service.
    """

    def send_sms(self, to: str, body: str, from_number: str = None) -> dict:
        """Simulate sending an SMS."""
        # Mask the phone number in logs — never log full numbers
        masked = to[:3] + "****" + to[-4:] if len(to) > 6 else "****"

        if to.endswith("0000"):
            logger.info(f"[DEMO] Simulated FAILURE to {masked}")
            return {
                "success": False,
                "provider_message_id": None,
                "error": "Demo: simulated delivery failure (number ends in 0000)",
            }

        # Generate a fake message ID that looks like a Twilio SID
        fake_sid = f"DEMO_{uuid.uuid4().hex[:24]}"
        logger.info(f"[DEMO] Simulated SUCCESS to {masked} — ID: {fake_sid}")
        return {
            "success": True,
            "provider_message_id": fake_sid,
            "error": None,
        }


class TwilioMessagingService:
    """
    Sends real SMS through the Twilio REST API.

    Requires TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_PHONE_NUMBER
    to be set in the environment / app config.
    """

    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        # Import here so the app doesn't crash if twilio isn't installed
        # and we're in demo mode
        from twilio.rest import Client

        self.client = Client(account_sid, auth_token)
        self.from_number = from_number

    def send_sms(self, to: str, body: str, from_number: str = None) -> dict:
        """
        Send an SMS via Twilio.

        Returns a result dict. Does NOT raise — catches Twilio exceptions
        and returns them as structured errors so the caller can continue
        processing other recipients.
        """
        from twilio.base.exceptions import TwilioRestException

        send_from = from_number or self.from_number
        masked = to[:3] + "****" + to[-4:] if len(to) > 6 else "****"

        try:
            message = self.client.messages.create(
                body=body,
                from_=send_from,
                to=to,
                # The status_callback URL is set in the Twilio console
                # or can be passed here if needed:
                # status_callback=url_for('webhooks.twilio_status', _external=True)
            )
            logger.info(f"[TWILIO] Submitted to {masked} — SID: {message.sid}")
            return {
                "success": True,
                "provider_message_id": message.sid,
                "error": None,
            }

        except TwilioRestException as e:
            logger.error(f"[TWILIO] Failed to {masked}: {e.msg}")
            return {
                "success": False,
                "provider_message_id": None,
                "error": f"Twilio error {e.code}: {e.msg}",
            }

        except Exception as e:
            # Network timeout or unexpected error — record as unknown
            logger.error(f"[TWILIO] Unknown error to {masked}: {str(e)}")
            return {
                "success": False,
                "provider_message_id": None,
                "error": f"Unknown error: {str(e)}",
            }


def get_messaging_service(app=None):
    """
    Factory: returns the right messaging service based on app config.

    Default is DemoMessagingService unless MESSAGING_MODE=twilio
    AND all required Twilio credentials are present.
    """
    if app is None:
        from flask import current_app
        app = current_app

    mode = app.config.get("MESSAGING_MODE", "demo")

    if mode == "twilio":
        sid = app.config.get("TWILIO_ACCOUNT_SID")
        token = app.config.get("TWILIO_AUTH_TOKEN")
        phone = app.config.get("TWILIO_PHONE_NUMBER")

        if sid and token and phone:
            return TwilioMessagingService(sid, token, phone)
        else:
            raise ValueError(
                "MESSAGING_MODE is set to 'twilio' but required Twilio credentials "
                "(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER) are missing."
            )

    return DemoMessagingService()
