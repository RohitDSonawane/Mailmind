"""
tests/conftest.py — Global test configuration.

Sets up dummy environment variables before any application modules
(like config.py) are imported, allowing tests to be collected without
a real .env file.
"""

import os

os.environ["GMAIL_ADDRESS"] = "test-bot@example.com"
os.environ["GMAIL_APP_PASSWORD"] = "test-app-password"
os.environ["GROQ_API_KEY"] = "gsk_test_mock_key"
os.environ["MEETING_DURATION_MINUTES"] = "60"
os.environ["POLL_INTERVAL_SECONDS"] = "30"
os.environ["DEFAULT_TIMEZONE"] = "UTC"
