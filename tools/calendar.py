"""
tools/calendar.py — Google Calendar API adapter.

Handles OAuth 2.0 token loading, token refresh, and the events.insert API call
to create calendar events for a scheduled meeting.
"""

import os
import logging
from datetime import datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/calendar']


def load_credentials(token_path: str = 'token.json', credentials_path: str = 'credentials.json') -> Credentials:
    """
    Load Google Calendar API credentials.

    If token_path exists, load from it. If expired, refresh.
    If it doesn't exist, run the local server OAuth flow.

    Parameters
    ----------
    token_path : str
        Path to the saved token file.
    credentials_path : str
        Path to the client secrets file.

    Returns
    -------
    Credentials
        The valid credentials object.

    Raises
    ------
    Exception
        On credential loading or OAuth flow failures.
    """
    creds = None
    try:
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        
        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(token_path, 'w') as token:
                    token.write(creds.to_json())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
                # Save the credentials for the next run
                with open(token_path, 'w') as token:
                    token.write(creds.to_json())
        return creds
    except Exception as e:
        logger.error(f"Failed to load credentials in google_calendar: {e}")
        raise


def create_event(title: str, utc_start: datetime, utc_end: datetime, attendee_addresses: list[str]) -> str:
    """
    Create a new event in the primary Google Calendar.

    NOTE: Idempotency is the caller's responsibility. The caller must ensure
    this is not called multiple times for the same logical meeting.

    Parameters
    ----------
    title : str
        The summary/title of the calendar event.
    utc_start : datetime
        The start time of the meeting in UTC.
    utc_end : datetime
        The end time of the meeting in UTC.
    attendee_addresses : list[str]
        A list of participant email addresses.

    Returns
    -------
    str
        The Google Calendar event ID of the newly created event.

    Raises
    ------
    ValueError
        If attendee_addresses is empty.
    HttpError
        On any API failure.
    """
    if not attendee_addresses:
        raise ValueError("Cannot create a calendar event with zero attendees.")

    try:
        creds = load_credentials()
        service = build('calendar', 'v3', credentials=creds)

        event_body = {
            'summary': title,
            'start': {
                'dateTime': utc_start.isoformat(),
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': utc_end.isoformat(),
                'timeZone': 'UTC',
            },
            'attendees': [{'email': address} for address in attendee_addresses]
        }

        event = service.events().insert(calendarId='primary', body=event_body).execute()
        
        event_id = event.get('id')
        if not event_id:
            raise ValueError("API returned success but no event ID was found in the response.")
            
        return event_id
    except HttpError as error:
        logger.error(f"HTTP Error in google_calendar create_event: status_code={error.status_code}, error={error}")
        raise
    except Exception as error:
        logger.error(f"Failed to create event in google_calendar: {error}")
        raise
