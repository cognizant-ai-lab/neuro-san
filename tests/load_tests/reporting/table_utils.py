"""Table formatting utilities for aligned log output."""

import logging

logger = logging.getLogger(__name__)


def log_table(header, rows):
    """Log an aligned table given a header list and list-of-lists rows."""
    col_widths = [len(h) for h in header]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(val)))
    fmt = "  ".join(f"{{:>{w}}}" for w in col_widths)
    logger.info("%s", fmt.format(*header))
    logger.info("%s", "-" * (sum(col_widths) + 2 * (len(header) - 1)))
    for row in rows:
        logger.info("%s", fmt.format(*row))
