"""
Entry point for running the CampusNotify application.

Usage:
    python run.py           # Runs on http://localhost:5000
    flask run               # Alternative using Flask CLI
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5001)
