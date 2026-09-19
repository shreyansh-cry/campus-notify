"""
CLI commands for database setup and demo data.

Usage:
    flask init-db          — Create all database tables
    flask create-organizer — Create the organizer login account
    flask seed-demo        — Populate fictional events and demo subscribers
"""

import click
from flask import current_app
from flask.cli import with_appcontext
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import Organizer, Event, Subscription
from app.helpers import generate_unsubscribe_token

from datetime import date, time, timedelta


@click.command("init-db")
@with_appcontext
def init_db_command():
    """Create all database tables."""
    db.create_all()
    click.echo("✓ Database tables created.")


@click.command("create-organizer")
@click.option("--username", prompt="Organizer username", help="Login username")
@click.option(
    "--password",
    prompt="Organizer password",
    hide_input=True,
    confirmation_prompt=True,
    help="Login password (will be hashed)",
)
@with_appcontext
def create_organizer_command(username, password):
    """Create the organizer account (prompts for credentials)."""
    # Check if an organizer already exists
    existing = Organizer.query.filter_by(username=username).first()
    if existing:
        click.echo(f"✗ Organizer '{username}' already exists.")
        return

    organizer = Organizer(username=username)
    organizer.set_password(password)
    db.session.add(organizer)
    db.session.commit()
    click.echo(f"✓ Organizer '{username}' created successfully.")


@click.command("reset-password")
@click.option("--username", prompt="Organizer username", help="Organizer username whose password to reset")
@click.option(
    "--password",
    prompt="New password",
    hide_input=True,
    confirmation_prompt=True,
    help="New password (will be hashed)",
)
@with_appcontext
def reset_password_command(username, password):
    """Reset the password for an existing organizer account."""
    organizer = Organizer.query.filter_by(username=username).first()
    if not organizer:
        click.echo(f"✗ Organizer '{username}' not found.")
        return

    organizer.set_password(password)
    db.session.commit()
    click.echo(f"✓ Password for organizer '{username}' updated successfully.")


@click.command("seed-demo")
@with_appcontext
def seed_demo_command():
    """Seed the database with fictional events and demo subscribers."""
    # Need at least one organizer
    organizer = Organizer.query.first()
    if not organizer:
        click.echo("✗ No organizer found. Run 'flask create-organizer' first.")
        return

    # Create 6 varied campus events
    today = date.today()
    events_data = [
        {
            "title": "Intro to Machine Learning Workshop",
            "club_name": "AI Club",
            "description": (
                "A beginner-friendly workshop covering the basics of machine learning. "
                "We'll explore supervised learning, build a simple classifier, and "
                "discuss real-world applications. Bring your laptop!"
            ),
            "event_date": today + timedelta(days=7),
            "event_time": time(14, 0),
            "location": "Room 301, CS Building",
        },
        {
            "title": "Annual Cultural Fest — Rhythms 2026",
            "club_name": "Cultural Committee",
            "description": (
                "Three days of music, dance, drama, and art. Featuring performances "
                "from college bands, a stand-up comedy night, and food stalls from "
                "local vendors. Open to all students."
            ),
            "event_date": today + timedelta(days=14),
            "event_time": time(17, 30),
            "location": "Main Auditorium & Open Ground",
        },
        {
            "title": "Resume Building & Interview Prep",
            "club_name": "Placement Cell",
            "description": (
                "Learn how to write a strong resume and handle technical interviews. "
                "Industry mentors will review your resume and conduct mock interviews. "
                "Limited seats — subscribe for a reminder!"
            ),
            "event_date": today + timedelta(days=10),
            "event_time": time(10, 0),
            "location": "Seminar Hall B",
        },
        {
            "title": "Hackathon: Build for Good",
            "club_name": "Developer Students Club",
            "description": (
                "A 24-hour hackathon focused on building technology solutions for "
                "social impact. Teams of 2-4. Prizes for Best Innovation, Best Design, "
                "and People's Choice. Meals and snacks provided."
            ),
            "event_date": today + timedelta(days=21),
            "event_time": time(9, 0),
            "location": "Innovation Lab, Block C",
        },
        {
            "title": "Photography Walk: Campus in Monsoon",
            "club_name": "Photography Club",
            "description": (
                "Join us for a guided photography walk around campus during monsoon. "
                "Learn composition tips, play with natural light, and capture the "
                "beauty of rain-soaked paths. All skill levels welcome."
            ),
            "event_date": today + timedelta(days=5),
            "event_time": time(7, 0),
            "location": "Meet at Library Entrance",
        },
        {
            "title": "Open Mic Night",
            "club_name": "Literary Society",
            "description": (
                "Poetry, prose, stand-up, music — bring whatever you want to share. "
                "A relaxed evening of creative expression. Sign up at the venue or "
                "just come to listen. Chai will be served!"
            ),
            "event_date": today + timedelta(days=3),
            "event_time": time(19, 0),
            "location": "Amphitheatre",
        },
    ]

    created_events = []
    for data in events_data:
        # Skip if event with same title already exists
        existing = Event.query.filter_by(title=data["title"]).first()
        if existing:
            created_events.append(existing)
            continue

        event = Event(organizer_id=organizer.id, **data)
        db.session.add(event)
        created_events.append(event)

    db.session.commit()
    click.echo(f"✓ {len(events_data)} events seeded.")

    # Add demo subscribers to the first 3 events
    demo_subscribers = [
        {"student_name": "Ananya Sharma", "phone_number": "+919876543210"},
        {"student_name": "Rahul Patel", "phone_number": "+919123456789"},
        {"student_name": "Priya Nair", "phone_number": "+918765432100"},
        # This number ends in 0000 — will simulate failure in demo mode
        {"student_name": "Demo Failure", "phone_number": "+911234560000"},
    ]

    sub_count = 0
    for event in created_events[:3]:
        for sub_data in demo_subscribers:
            existing = Subscription.query.filter_by(
                event_id=event.id, phone_number=sub_data["phone_number"]
            ).first()
            if existing:
                continue

            sub = Subscription(
                event_id=event.id,
                student_name=sub_data["student_name"],
                phone_number=sub_data["phone_number"],
                consent_given=True,
                is_active=True,
                unsubscribe_token=generate_unsubscribe_token(),
            )
            db.session.add(sub)
            sub_count += 1

    db.session.commit()
    click.echo(f"✓ {sub_count} demo subscriptions created.")
    click.echo(
        "\nNote: Subscriber 'Demo Failure' (ending in 0000) will simulate "
        "a delivery failure in demo mode."
    )
