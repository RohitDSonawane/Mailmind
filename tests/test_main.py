import pytest
from unittest.mock import MagicMock, call
import main

def test_polling_no_messages(mocker):
    mocker.patch("main.sqlite3.connect")
    mocker.patch("main.dal.initialize_schema")
    mocker.patch("main.gmail_reader.connect", return_value="imap")
    mocker.patch("main.gmail_sender.connect", return_value="smtp")
    
    mock_fetch = mocker.patch("main.gmail_reader.fetch_unseen", return_value=[])
    mock_pipeline = mocker.patch("main.run_pipeline")
    mock_sleep = mocker.patch("main.time.sleep", side_effect=KeyboardInterrupt)

    main.main()

    mock_fetch.assert_called_once_with("imap")
    mock_pipeline.assert_not_called()
    mock_sleep.assert_called_once()

def test_polling_one_message_success(mocker):
    mocker.patch("main.sqlite3.connect")
    mocker.patch("main.dal.initialize_schema")
    mocker.patch("main.gmail_reader.connect", return_value="imap")
    mocker.patch("main.gmail_sender.connect", return_value="smtp")
    
    mock_msg = MagicMock()
    mock_msg.message_id = "msg1"
    mock_msg.uid = b"1"
    
    mock_fetch = mocker.patch("main.gmail_reader.fetch_unseen", return_value=[mock_msg])
    mock_is_processed = mocker.patch("main.dal.is_processed", return_value=False)
    mock_pipeline = mocker.patch("main.run_pipeline")
    mock_mark_processed = mocker.patch("main.dal.mark_processed")
    mock_mark_seen = mocker.patch("main.gmail_reader.mark_seen")
    mock_sleep = mocker.patch("main.time.sleep", side_effect=KeyboardInterrupt)
    
    # Track order of calls to ensure mark_seen happens after mark_processed
    manager = MagicMock()
    manager.attach_mock(mock_mark_processed, 'mark_processed')
    manager.attach_mock(mock_mark_seen, 'mark_seen')

    main.main()

    mock_pipeline.assert_called_once()
    mock_mark_processed.assert_called_once()
    mock_mark_seen.assert_called_once_with("imap", b"1")
    
    # Assert ordering
    assert manager.mock_calls[0][0] == 'mark_processed'
    assert manager.mock_calls[1][0] == 'mark_seen'

def test_polling_one_message_already_processed(mocker):
    mocker.patch("main.sqlite3.connect")
    mocker.patch("main.dal.initialize_schema")
    mocker.patch("main.gmail_reader.connect", return_value="imap")
    mocker.patch("main.gmail_sender.connect", return_value="smtp")
    
    mock_msg = MagicMock()
    mock_msg.message_id = "msg1"
    mock_msg.uid = b"1"
    
    mock_fetch = mocker.patch("main.gmail_reader.fetch_unseen", return_value=[mock_msg])
    mock_is_processed = mocker.patch("main.dal.is_processed", return_value=True)
    mock_pipeline = mocker.patch("main.run_pipeline")
    mock_mark_processed = mocker.patch("main.dal.mark_processed")
    mock_mark_seen = mocker.patch("main.gmail_reader.mark_seen")
    mock_sleep = mocker.patch("main.time.sleep", side_effect=KeyboardInterrupt)

    main.main()

    mock_pipeline.assert_not_called()
    mock_mark_processed.assert_not_called()
    mock_mark_seen.assert_called_once_with("imap", b"1")

def test_polling_pipeline_raises(mocker):
    mocker.patch("main.sqlite3.connect")
    mocker.patch("main.dal.initialize_schema")
    mocker.patch("main.gmail_reader.connect", return_value="imap")
    mocker.patch("main.gmail_sender.connect", return_value="smtp")
    
    mock_msg = MagicMock()
    mock_msg.message_id = "msg1"
    mock_msg.uid = b"1"
    
    mock_fetch = mocker.patch("main.gmail_reader.fetch_unseen", return_value=[mock_msg])
    mock_is_processed = mocker.patch("main.dal.is_processed", return_value=False)
    mock_pipeline = mocker.patch("main.run_pipeline", side_effect=Exception("test error"))
    mock_mark_processed = mocker.patch("main.dal.mark_processed")
    mock_mark_seen = mocker.patch("main.gmail_reader.mark_seen")
    mock_sleep = mocker.patch("main.time.sleep", side_effect=KeyboardInterrupt)

    main.main()

    mock_pipeline.assert_called_once()
    mock_mark_processed.assert_not_called()
    mock_mark_seen.assert_not_called()

def test_polling_fetch_raises(mocker):
    mocker.patch("main.sqlite3.connect")
    mocker.patch("main.dal.initialize_schema")
    mocker.patch("main.gmail_reader.connect", return_value="imap")
    mocker.patch("main.gmail_sender.connect", return_value="smtp")
    
    mock_fetch = mocker.patch("main.gmail_reader.fetch_unseen", side_effect=Exception("imap error"))
    mock_reconnect = mocker.patch("main._reconnect", return_value=("imap2", "smtp2"))
    
    def side_effect_sleep(*args, **kwargs):
        raise KeyboardInterrupt()

    mock_sleep = mocker.patch("main.time.sleep", side_effect=side_effect_sleep)

    main.main()

    mock_reconnect.assert_called_once()
    mock_sleep.assert_called_once()

def test_reconnect_success(mocker):
    mock_imap = MagicMock()
    mock_smtp = MagicMock()
    
    mock_gmail_connect = mocker.patch("main.gmail_reader.connect", return_value="new_imap")
    mock_smtp_connect = mocker.patch("main.gmail_sender.connect", return_value="new_smtp")
    
    new_imap, new_smtp = main._reconnect(mock_imap, mock_smtp)
    
    mock_imap.logout.assert_called_once()
    mock_smtp.quit.assert_called_once()
    assert new_imap == "new_imap"
    assert new_smtp == "new_smtp"
