"""
Tests for organizer authentication and access protection.

Covers:
- Organizer routes require login
- Invalid credentials are rejected
- Valid login + logout flow
"""


class TestAccessProtection:
    """Verify that organizer routes redirect unauthenticated users."""

    PROTECTED_ROUTES = [
        "/organizer/dashboard",
        "/organizer/events",
        "/organizer/events/new",
        "/organizer/notifications",
    ]

    def test_protected_routes_redirect_to_login(self, client, organizer):
        """All organizer routes should redirect to login if not authenticated."""
        for route in self.PROTECTED_ROUTES:
            resp = client.get(route)
            assert resp.status_code in (302, 308), f"{route} should redirect"
            assert "/organizer/login" in resp.headers.get("Location", "")

    def test_event_detail_requires_login(self, client, sample_event):
        """Organizer event detail page requires login."""
        resp = client.get(f"/organizer/events/{sample_event.id}")
        assert resp.status_code == 302
        assert "/organizer/login" in resp.headers.get("Location", "")


class TestLogin:
    """Verify login and logout behavior."""

    def test_login_page_renders(self, client):
        """Login page should render with a form."""
        resp = client.get("/organizer/login")
        assert resp.status_code == 200
        assert b"Organizer Login" in resp.data

    def test_valid_login(self, client, organizer):
        """Valid credentials should redirect to dashboard."""
        resp = client.post("/organizer/login", data={
            "username": "testadmin",
            "password": "testpass123",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Dashboard" in resp.data

    def test_invalid_password(self, client, organizer):
        """Wrong password should show error and stay on login page."""
        resp = client.post("/organizer/login", data={
            "username": "testadmin",
            "password": "wrongpassword",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Invalid username or password" in resp.data

    def test_invalid_username(self, client, organizer):
        """Non-existent username should show error."""
        resp = client.post("/organizer/login", data={
            "username": "nobody",
            "password": "testpass123",
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b"Invalid username or password" in resp.data

    def test_logout(self, auth_client):
        """Logging out should redirect and remove access."""
        resp = auth_client.post("/organizer/logout", follow_redirects=True)
        assert resp.status_code == 200
        # After logout, accessing dashboard should redirect to login
        resp = auth_client.get("/organizer/dashboard")
        assert resp.status_code == 302
