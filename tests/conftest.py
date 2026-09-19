"""
Test fixtures for CampusNotify.

Provides:
- app: Flask app configured for testing (SQLite in-memory, CSRF disabled)
- client: Flask test client for making HTTP requests
- db_session: Fresh database for each test
- auth_client: Pre-authenticated test client (logged in as organizer)
- sample_event: A ready-made event for testing
"""

import pytest
from datetime import date, time, timedelta

from app import create_app
from app.extensions import db as _db
from app.models import Organizer, Event, Subscription
from app.helpers import generate_unsubscribe_token


@pytest.fixture(scope="session")
def app():
    """Create the Flask application with testing config."""
    app = create_app("testing")
    return app


@pytest.fixture(autouse=True)
def db_session(app):
    """
    Create fresh database tables before each test, drop after.

    This ensures every test starts with a clean database.
    """
    with app.app_context():
        _db.create_all()
        yield _db
        _db.session.rollback()
        _db.drop_all()


@pytest.fixture
def client(app):
    """Flask test client for making HTTP requests."""
    return app.test_client()


@pytest.fixture
def organizer(db_session):
    """Create a test organizer account."""
    org = Organizer(username="testadmin")
    org.set_password("testpass123")
    db_session.session.add(org)
    db_session.session.commit()
    return org


@pytest.fixture
def auth_client(client, organizer):
    """
    A test client that is already logged in as the organizer.

    Uses the test client's POST to /organizer/login to establish a session.
    """
    client.post("/organizer/login", data={
        "username": "testadmin",
        "password": "testpass123",
    })
    return client


@pytest.fixture
def sample_event(db_session, organizer):
    """Create a sample upcoming event for testing."""
    event = Event(
        organizer_id=organizer.id,
        title="Test Workshop",
        club_name="Test Club",
        description="A test event for unit testing.",
        event_date=date.today() + timedelta(days=7),
        event_time=time(14, 0),
        location="Room 101",
    )
    db_session.session.add(event)
    db_session.session.commit()
    return event


@pytest.fixture
def sample_subscription(db_session, sample_event):
    """Create a sample active subscription for testing."""
    sub = Subscription(
        event_id=sample_event.id,
        student_name="Test Student",
        phone_number="+919876543210",
        consent_given=True,
        is_active=True,
        unsubscribe_token=generate_unsubscribe_token(),
    )
    db_session.session.add(sub)
    db_session.session.commit()
    return sub


@pytest.fixture
def cancelled_event(db_session, organizer):
    """Create a cancelled event for testing."""
    event = Event(
        organizer_id=organizer.id,
        title="Cancelled Event",
        club_name="Test Club",
        description="This event was cancelled.",
        event_date=date.today() + timedelta(days=14),
        event_time=time(10, 0),
        location="Room 202",
        is_cancelled=True,
    )
    db_session.session.add(event)
    db_session.session.commit()
    return event
