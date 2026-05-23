import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone
from googleapiclient.errors import HttpError
from tools import calendar

def test_load_credentials_existing_valid(mocker):
    mock_exists = mocker.patch("os.path.exists", return_value=True)
    mock_creds = MagicMock()
    mock_creds.valid = True
    mock_from_file = mocker.patch("tools.calendar.Credentials.from_authorized_user_file", return_value=mock_creds)
    mock_flow = mocker.patch("tools.calendar.InstalledAppFlow")

    creds = calendar.load_credentials("token.json", "credentials.json")
    assert creds == mock_creds
    mock_from_file.assert_called_once_with("token.json", calendar.SCOPES)
    mock_flow.assert_not_called()

def test_load_credentials_expired_refresh(mocker):
    mock_exists = mocker.patch("os.path.exists", return_value=True)
    mock_creds = MagicMock()
    mock_creds.valid = False
    mock_creds.expired = True
    mock_creds.refresh_token = "some_token"
    mock_creds.to_json.return_value = '{"token": "new"}'
    
    mock_from_file = mocker.patch("tools.calendar.Credentials.from_authorized_user_file", return_value=mock_creds)
    mock_flow = mocker.patch("tools.calendar.InstalledAppFlow")
    mocker.patch("builtins.open", mocker.mock_open())

    creds = calendar.load_credentials("token.json", "credentials.json")
    assert creds == mock_creds
    mock_creds.refresh.assert_called_once()
    mock_flow.assert_not_called()

def test_create_event_valid(mocker):
    mocker.patch("tools.calendar.load_credentials", return_value=MagicMock())
    mock_build = mocker.patch("tools.calendar.build")
    
    mock_service = MagicMock()
    mock_build.return_value = mock_service
    
    mock_insert = mock_service.events().insert
    mock_insert.return_value.execute.return_value = {"id": "test-event-id-123"}
    
    start = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    end = datetime(2025, 1, 1, 11, 0, tzinfo=timezone.utc)
    
    event_id = calendar.create_event("Sync", start, end, ["a@example.com"])
    assert event_id == "test-event-id-123"
    
    mock_insert.assert_called_once()
    kwargs = mock_insert.call_args.kwargs
    assert kwargs["calendarId"] == "primary"
    body = kwargs["body"]
    assert body["summary"] == "Sync"
    assert body["start"]["timeZone"] == "UTC"
    assert body["end"]["dateTime"] == "2025-01-01T11:00:00+00:00"
    assert body["attendees"] == [{"email": "a@example.com"}]

def test_create_event_raises_http_error(mocker):
    mocker.patch("tools.calendar.load_credentials", return_value=MagicMock())
    mock_build = mocker.patch("tools.calendar.build")
    mock_service = MagicMock()
    mock_build.return_value = mock_service
    
    mock_insert = mock_service.events().insert
    import httplib2
    resp = httplib2.Response({"status": 403})
    mock_insert.return_value.execute.side_effect = HttpError(resp, b"Forbidden")
    
    start = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    end = datetime(2025, 1, 1, 11, 0, tzinfo=timezone.utc)
    
    with pytest.raises(HttpError):
        calendar.create_event("Sync", start, end, ["a@example.com"])
