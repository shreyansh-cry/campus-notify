"""
Twilio delivery-status webhook.

When Twilio sends a message, it can POST status updates to this endpoint.
We use it to track whether messages were actually delivered or failed.

Security:
- Validates Twilio request signatures to prevent spoofing.
- CSRF is exempted because this is called by Twilio's servers, not a browser.

Status progression:
- Only updates if the new status is "more final" than the current one.
- Never overwrites delivered/failed with an earlier status like 'sent'.
"""

import logging
from flask import Blueprint, request, current_app, abort

from app.extensions import db, csrf
from app.models import Notification

logger = logging.getLogger(__name__)

webhooks_bp = Blueprint("webhooks", __name__)


def validate_twilio_signature(req):
    """
    Validate that the incoming request is genuinely from Twilio.

    Uses Twilio's RequestValidator to check the X-Twilio-Signature header
    against the request URL and POST parameters.

    Returns True if valid, False otherwise.
    """
    from twilio.request_validator import RequestValidator

    auth_token = current_app.config.get("TWILIO_AUTH_TOKEN", "")
    if not auth_token:
        logger.warning("No TWILIO_AUTH_TOKEN configured — cannot validate webhook.")
        return False

    validator = RequestValidator(auth_token)
    signature = req.headers.get("X-Twilio-Signature", "")
    url = req.url

    # Twilio sends POST data as form parameters
    return validator.validate(url, req.form.to_dict(), signature)


@webhooks_bp.route("/webhooks/twilio/status", methods=["POST"])
@csrf.exempt  # Twilio sends POST requests without CSRF tokens
def twilio_status():
    """
    Handle Twilio delivery status callbacks.

    Twilio sends updates like: queued → sent → delivered (or failed).
    We look up the notification by the Twilio Message SID and update
    the status — but only if the new status is more final.

    Always returns 200 to prevent Twilio from retrying.
    """
    # Only validate signatures in Twilio mode
    if current_app.config.get("MESSAGING_MODE") == "twilio":
        if not validate_twilio_signature(request):
            logger.warning("Invalid Twilio webhook signature — rejecting request.")
            abort(403)

    # Extract fields from the Twilio callback
    message_sid = request.form.get("MessageSid", "")
    message_status = request.form.get("MessageStatus", "").lower()

    if not message_sid or not message_status:
        logger.warning("Webhook received without MessageSid or MessageStatus.")
        return "", 200  # Don't retry

    # Find the notification record
    notification = Notification.query.filter_by(
        provider_message_id=message_sid
    ).first()

    if not notification:
        # Unknown message — could be from a different app or old data
        logger.info(f"Webhook for unknown MessageSid: {message_sid}")
        return "", 200

    # Status progression check — don't let 'sent' overwrite 'delivered'
    if notification.can_update_to(message_status):
        old_status = notification.status
        notification.status = message_status
        db.session.commit()
        logger.info(
            f"Notification {notification.id}: {old_status} → {message_status}"
        )
    else:
        logger.info(
            f"Notification {notification.id}: ignoring {message_status} "
            f"(current: {notification.status})"
        )

    return "", 200
