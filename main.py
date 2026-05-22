"""
main.py — MailMind entry point.

Phase 01: stub only. The polling loop is implemented in Phase 10.
Importing this module verifies the full package tree is intact.
"""

import logging

logger = logging.getLogger(__name__)


def main() -> None:
    """Entry point — polling loop added in Phase 10."""
    logger.info("MailMind starting up (scaffold phase — no polling loop yet).")


if __name__ == "__main__":
    import config  # noqa: F401 — triggers validation on direct run
    main()
