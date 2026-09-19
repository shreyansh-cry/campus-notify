# CampusNotify

A college event reminder application built with Python and Flask. Organizers manage events, students subscribe to reminders, and notification records track each reminder attempt.

CampusNotify is a student portfolio project. It demonstrates authentication, database relationships, messaging integration, failure handling, and automated testing.

**Demo mode is enabled by default. No real SMS is sent in demo mode.**

## Features

- Create, edit, and cancel college events.
- Browse upcoming events without a student account.
- Subscribe using a name, phone number, and explicit consent.
- Unsubscribe through a unique token link.
- Send reminders manually from an authenticated organizer dashboard.
- Send subsequent batches to newly eligible subscribers without repeating earlier attempts.
- View notification history and message statuses.
- Simulate successful and failed message submissions without Twilio credentials.
- Protect organizer actions with authentication and CSRF checks.

## How It Works

### Organizer

1. Log in to the organizer dashboard.
2. Create an event with its title, club, date, time, and location.
3. View active subscriptions and the number eligible for a reminder.
4. Click **Send to N new subscribers** and confirm.
5. Review notification history for submission and delivery statuses.

### Student

1. Open the public homepage and select an upcoming event.
2. Enter a name and phone number.
3. Agree to receive reminders and subscribe.
4. In live mode, receive an SMS when the organizer sends a reminder and delivery succeeds.
5. Use the subscription's unique unsubscribe link to stop future reminders.

Students do not need accounts and do not have an in-app notification inbox.

In demo mode, no SMS arrives on a phone. The simulated attempt appears in the organizer's notification history.

## Incremental Reminders

Reminder eligibility is tracked per subscription, rather than through a single event-level “already sent” flag.

A subscription is eligible when:

- The event is upcoming and not cancelled.
- The subscription is active.
- Consent is recorded.
- No standard notification record exists for that subscription.

Example:

| Action | New reminder attempts |
| --- | --- |
| A subscribes; organizer sends | A only |
| B subscribes later; organizer sends again | B only |
| Organizer sends again without new eligible subscribers | None |
| C and D subscribe; organizer sends again | C and D only |

A database constraint on `subscription_id` and `reminder_type` prevents duplicate standard notification records.

Existing records are excluded regardless of status, including `pending`, `sent`, `delivered`, and `failed`. Failed or uncertain attempts are not automatically retried.

A recorded attempt does not guarantee delivery.

## Technology Stack

| Component | Technology |
| --- | --- |
| Language | Python |
| Web framework | Flask |
| Templates and interface | Jinja2, Bootstrap, HTML, CSS |
| Database access | Flask-SQLAlchemy / SQLAlchemy |
| Verified local database | SQLite |
| Organizer authentication | Flask-Login |
| Password hashing | Werkzeug, using scrypt in the tested environment |
| Browser form protection | Flask-WTF |
| Login rate limiting | Flask-Limiter |
| Messaging integration | Twilio Python SDK |
| Environment configuration | python-dotenv |
| Automated testing | pytest, pytest-cov |

The application has MySQL configuration support through PyMySQL, but MySQL execution has not been verified. The reported tests use SQLite.

## Local Setup

### Prerequisites

- Python 3.10 or later
- pip
- Git

Exact dependency versions are listed in `requirements.txt`.

### 1. Clone the repository

```bash
git clone https://github.com/shreyansh-cry/campus-notify.git
cd campus-notify
```

### 2. Create a virtual environment

```bash
python3 -m venv venv
```

Activate it on macOS or Linux:

```bash
source venv/bin/activate
```

On Windows Command Prompt:

```bat
venv\Scripts\activate
```

### 3. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 4. Configure the environment

On macOS or Linux:

```bash
cp .env.example .env
```

On Windows Command Prompt:

```bat
copy .env.example .env
```

Open `.env` and configure:

```dotenv
FLASK_APP=run.py
FLASK_CONFIG=development
FLASK_SECRET_KEY=replace-with-a-long-random-string
MESSAGING_MODE=demo
```

Keep any other settings required by `.env.example`.

Generate a random secret key with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Copy the generated value into `FLASK_SECRET_KEY` in your local `.env`.

Do not commit `.env`, passwords, API credentials, or local databases.

### 5. Initialize the database

For a new local installation:

```bash
flask init-db
```

The default local SQLite database is stored at:

```text
instance/campus_notify.db
```

### 6. Create an organizer account

```bash
flask create-organizer
```

Follow the prompts to choose a username and password. There are no organizer credentials published in this repository.

### 7. Optionally add demo data

For a new demo installation:

```bash
flask seed-demo
```

This adds fictional events and subscriptions for exploring the app.

### 8. Start the website

```bash
python run.py
```

The documented development entry point uses port **5001**.

| Page | URL |
| --- | --- |
| Student homepage | http://127.0.0.1:5001/ |
| Organizer login | http://127.0.0.1:5001/organizer/login |
| Organizer dashboard | http://127.0.0.1:5001/organizer/dashboard |

Keep the terminal running while using the website.

`python run.py` starts a local development server with debugging enabled. It is not a production hosting command.

## Quick Demo

Use two separate browser sessions:

- **Normal window:** organizer account.
- **Incognito/private window:** anonymous student.

### First reminder

1. As organizer, create an event scheduled for tomorrow.
2. In the student window, subscribe as Student A with consent.
3. Refresh the organizer event page.
4. Confirm that one subscriber is eligible.
5. Send the reminder.
6. Confirm that one simulated notification record appears.

### Late subscriber

1. Subscribe Student B to the same event using a different test number.
2. Refresh the organizer event page.
3. Send to the newly eligible subscriber.
4. Confirm that B gets a notification record and A gets no additional record.

### Unsubscribe

1. Subscribe another fictional student to an unsent event.
2. Use that student's unsubscribe link before sending.
3. Confirm that the inactive subscription is excluded.

### Simulated failure

1. Subscribe a fictional, valid-format phone number ending in `0000`.
2. Send its reminder.
3. Confirm that the notification shows a simulated failure.

Use fictional data when demonstrating the application.

## Demo Messaging

When `MESSAGING_MODE=demo`:

- Numbers not ending in `0000` simulate successful submission.
- Numbers ending in `0000` simulate a provider failure.
- Successful submissions receive a fake message identifier beginning with `DEMO_`.
- The demo messaging service does not call Twilio.
- No real SMS is sent.

A simulated `sent` status is not proof of delivery to a phone.

## Twilio Integration

The project includes a Twilio messaging service and a delivery-status webhook handler.

Real messaging requires explicitly selecting Twilio mode and configuring valid credentials:

```dotenv
MESSAGING_MODE=twilio
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=your_twilio_sender_number
```

Selecting Twilio mode without required credentials raises a configuration error.

Account permissions, sender and recipient restrictions, and a publicly reachable callback endpoint must also be configured for real use. Credentials alone do not verify delivery.

**Real SMS delivery and live webhook callbacks have not been verified for this project.** Automated tests use mocks for external messaging behavior.

## Running Tests

Activate the virtual environment, then run:

```bash
python -m pytest
```

To display individual test results:

```bash
python -m pytest -v
```

To generate a coverage report:

```bash
python -m pytest --cov=app --cov-report=term-missing
```

The latest reported verification completed with:

```text
82 passed, 0 failed, 0 skipped, 0 warnings
```

Tests cover:

- Organizer login, logout, and protected routes.
- Password hashing and tampered session cookies.
- CSRF protection and login rate limiting.
- Event management and input validation.
- Subscriptions, consent, unsubscribe, and resubscribe behavior.
- Incremental reminder eligibility and duplicate prevention.
- Messaging failures and notification transaction behavior.
- Webhook signature checks and status handling.
- Production configuration checks.

The test suite uses isolated SQLite databases and simulated or mocked messaging. It is intended to run without contacting Twilio or changing the normal local database.

Passing tests establish the tested behaviors, not complete security or production readiness.

## Resetting an Organizer Password

With the virtual environment active:

```bash
flask reset-password
```

Follow the prompts for the username and new password.

## Security and Privacy

Implemented controls include:

- Hashed organizer passwords.
- Authentication on organizer routes.
- CSRF protection for browser forms.
- Login rate limiting.
- Masked phone numbers in the organizer interface.
- Token-based unsubscribe links.
- Twilio webhook signature verification.
- Production configuration checks for missing or known default secret keys.
- Git exclusions for environment files, databases, and virtual environments.

These controls do not replace deployment-specific security review.

## Known Limitations

- **Real SMS:** End-to-end Twilio delivery has not been verified.
- **MySQL:** Configuration support exists, but execution and concurrency have not been verified against MySQL.
- **Public hosting:** Deployment, HTTPS, proxy trust settings, and production operation remain unverified.
- **Manual reminders:** The organizer clicks Send. There is no automatic scheduler.
- **Organizer permissions:** Organizer accounts share access to event management; the app does not provide separate club ownership permissions.
- **Retries:** Existing standard notification attempts are skipped, including failed and pending attempts. There is no dedicated retry workflow.
- **Interrupted sends:** The notification record is committed before provider submission. A crash can leave a pending record without confirmed submission or delivery. Automatic reconciliation is not implemented.
- **Delivery guarantees:** Duplicate-record prevention does not establish exactly-once external SMS delivery.
- **Rate limiting:** The current in-memory limiter does not share counters between server processes and loses counters on restart.
- **Scale:** The application targets small demonstration workloads. Production-scale throughput and latency have not been measured.

Do not delete notification history to bypass duplicate protection.

## Project Structure

| Path | Purpose |
| --- | --- |
| `app/__init__.py` | Application factory and initialization |
| `app/models.py` | Organizer, Event, Subscription, and Notification models |
| `app/auth.py` | Organizer login and logout |
| `app/organizer.py` | Event management and reminder sending |
| `app/student.py` | Public events, subscriptions, and unsubscribe |
| `app/messaging.py` | Demo and Twilio messaging services |
| `app/webhooks.py` | Delivery-status callback handling |
| `app/commands.py` | Database and account-management commands |
| `app/helpers.py` | Formatting, masking, and utility functions |
| `app/config.py` | Application configuration |
| `app/extensions.py` | Flask extension setup |
| `app/templates/` | Jinja2 page templates |
| `app/static/` | Styles and other static assets |
| `tests/` | Automated test suite |
| `.github/workflows/tests.yml` | Automated test workflow |
| `run.py` | Local development entry point |
| `requirements.txt` | Python dependencies |
| `pytest.ini` | Test configuration |
| `.env.example` | Environment template with placeholders |

## License

No license has been added to this repository.
