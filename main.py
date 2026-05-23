"""
main.py — MailMind entry point.

Implements the top-level polling loop: initializes connections,
fetches unseen messages, calls run_pipeline, marks messages as
processed, and handles retries/reconnections.
"""

import logging
import time
import sqlite3
import traceback
from datetime import datetime, timezone

import config
from tools import gmail_reader, gmail_sender
from database import dal
from pipeline.handler import run_pipeline

logger = logging.getLogger(__name__)


def log_error(exception: Exception, message_id: str | None) -> None:
    """Log an error with structure."""
    exc_type = type(exception).__name__
    exc_message = str(exception)
    msg_id_str = message_id if message_id else "n/a"
    tb = traceback.format_exc()
    logger.error(f"Error [{exc_type}] on message {msg_id_str}: {exc_message}\n{tb}")


def _reconnect(imap_conn, smtp_conn) -> tuple:
    """Attempt to reconnect IMAP and SMTP."""
    logger.info("Attempting to reconnect IMAP and SMTP...")
    try:
        if imap_conn:
            try:
                imap_conn.logout()
            except Exception:
                pass
        if smtp_conn:
            try:
                smtp_conn.quit()
            except Exception:
                pass
    except Exception:
        pass

    try:
        new_imap_conn = gmail_reader.connect(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
        new_smtp_conn = gmail_sender.connect(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
        logger.info("Reconnection successful.")
        return new_imap_conn, new_smtp_conn
    except Exception as e:
        logger.error(f"Reconnection failed: {e}")
        raise


def main() -> None:
    """Entry point — infinite polling loop."""
    conn = sqlite3.connect('mailmind.db')
    conn.row_factory = sqlite3.Row
    dal.initialize_schema(conn)

    imap_conn = gmail_reader.connect(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
    smtp_conn = gmail_sender.connect(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)

    logger.info(f"MailMind starting up. Bot address: {config.GMAIL_ADDRESS}")
    logger.info(f"Poll interval: {config.POLL_INTERVAL_SECONDS}s, Meeting duration: {config.MEETING_DURATION_MINUTES}m")

    while True:
        try:
            try:
                # Issue NOOP to synchronize mailbox state with the server
                # Keep SMTP connection alive or reconnect
                if hasattr(smtp_conn, "noop"):
                    try:
                        smtp_conn.noop()
                    except Exception:
                        logger.info("SMTP connection lost. Reconnecting...")
                        smtp_conn = gmail_sender.connect(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)

                if hasattr(imap_conn, "noop"):
                    imap_conn.noop()
                messages = gmail_reader.fetch_unseen(imap_conn)
                for message in messages:
                    if dal.is_processed(conn, message.message_id):
                        gmail_reader.mark_seen(imap_conn, message.uid)
                        continue
                    try:
                        current_utc = datetime.now(timezone.utc).isoformat()
                        run_pipeline(conn, imap_conn, smtp_conn, message, current_utc)
                        dal.mark_processed(conn, message.message_id, current_utc)
                        conn.commit()
                        gmail_reader.mark_seen(imap_conn, message.uid)
                    except Exception as e:
                        log_error(e, message.message_id)
                        # message remains unseen; will be retried on next poll cycle
                
                try:
                    time.sleep(config.POLL_INTERVAL_SECONDS)
                except InterruptedError:
                    pass
            except Exception as poll_level_error:
                log_error(poll_level_error, None)
                # attempt reconnection before next cycle
                imap_conn, smtp_conn = _reconnect(imap_conn, smtp_conn)
                try:
                    time.sleep(config.POLL_INTERVAL_SECONDS)
                except InterruptedError:
                    pass
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received. Exiting polling loop.")
            break


if __name__ == "__main__":
    main()
