"""
Advanced authentication tests.

Covers:
- Password hashing verification
- All organizer endpoints logged-out access
- Tampered session cookies
"""

from app.models import Organizer
from werkzeug.security import check_password_hash
from flask import session
import pytest

class TestAdvancedAuth:
    
    def test_password_is_hashed(self, organizer):
        """Passwords must be hashed, not stored in plaintext."""
        assert organizer.password_hash != "testpass123"
        assert organizer.password_hash.startswith("scrypt:") or organizer.password_hash.startswith("pbkdf2:")
        assert check_password_hash(organizer.password_hash, "testpass123")
        
    def test_all_organizer_endpoints_protected(self, client, sample_event):
        """Ensure every single organizer endpoint requires login."""
        endpoints = [
            ("GET", "/organizer/dashboard"),
            ("GET", "/organizer/events"),
            ("GET", "/organizer/events/new"),
            ("POST", "/organizer/events/new"),
            ("GET", f"/organizer/events/{sample_event.id}"),
            ("GET", f"/organizer/events/{sample_event.id}/edit"),
            ("POST", f"/organizer/events/{sample_event.id}/edit"),
            ("POST", f"/organizer/events/{sample_event.id}/cancel"),
            ("GET", f"/organizer/events/{sample_event.id}/send"),
            ("POST", f"/organizer/events/{sample_event.id}/send"),
            ("GET", "/organizer/notifications"),
            ("POST", "/organizer/logout"),
        ]
        
        for method, url in endpoints:
            if method == "GET":
                resp = client.get(url)
            else:
                resp = client.post(url, data={})
                
            assert resp.status_code in (302, 308), f"{method} {url} is not protected!"
            assert "/organizer/login" in resp.headers.get("Location", "")
            
    def test_tampered_session_cookie(self, client, app):
        """Tampering with the session cookie should invalidate the session."""
        # We use a clean client and send a tampered cookie.
        # It should NOT be treated as logged in.
        client.set_cookie("session", "tampered_fake_cookie_value", domain="localhost")
        resp = client.get("/organizer/dashboard")
        assert resp.status_code == 302
        assert "/organizer/login" in resp.headers.get("Location", "")
