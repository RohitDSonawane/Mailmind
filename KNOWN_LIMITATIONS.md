# MailMind — Known Limitations

The following limitations are known and expected behavior in this version of MailMind:

- **Address Aliasing**: If a participant replies from a different email address than the one they were originally invited from (e.g. they were emailed at `user@domain.com` but replied from `user+alias@domain.com`), their reply is currently discarded as an "unknown sender".
- **Thread Inactivity / Timeouts**: Scheduling threads remain open indefinitely if participants stop responding. There is no automated timeout or garbage collection of stale threads.
- **Duplicate Calendar Events**: It is theoretically possible (with extremely low probability) to create duplicate calendar events if the application process crashes in the precise millisecond window between the Google Calendar API `events.insert` successfully returning an event and the SQLite database transaction committing the `calendar_event_id` to disk.
- **Graceful Shutdown**: On Unix-like systems, the `SIGTERM` signal does not trigger a graceful shutdown of the polling loop—only `SIGINT` (Ctrl-C) does. Operators on Unix systems should terminate the process using Ctrl-C or `kill -INT`.
- **First Run Setup**: The first run of the application on a new machine requires an interactive browser session for Google OAuth to generate the initial `token.json`. All subsequent runs are fully headless and maintain their own token refreshes.
- **SQLite Performance**: Because MailMind relies on a local SQLite database, horizontally scaling the application across multiple servers is not supported and will lead to database locking issues. MailMind is designed to run as a single process.
