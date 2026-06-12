"""Disconnection reporting — aggregate client disconnection analysis."""

import logging

logger = logging.getLogger(__name__)


def log_disconnection_summary(stage_summaries):
    """Log aggregate client disconnection report across all batches."""
    all_disconnections = []
    for idx, stage in enumerate(stage_summaries):
        for disc in stage.get("disconnections") or []:
            disc_copy = dict(disc)
            disc_copy["batch"] = idx + 1
            all_disconnections.append(disc_copy)
    if not all_disconnections:
        return
    logger.info("\n%s", "=" * 60)
    logger.info(
        "  CLIENT DISCONNECTIONS (%s detected in server log)",
        len(all_disconnections),
    )
    logger.info("=" * 60)
    for disc in all_disconnections:
        logger.info(
            "  Batch %s: %s — %s still processing at disconnect",
            disc.get("batch", "?"),
            disc.get("request_id", "unknown"),
            disc.get("agent", "unknown"),
        )
    logger.info(
        "\n  These requests had their client disconnect"
        "\n  before the server finished. The server detected the"
        "\n  disconnection and cancelled in-flight tasks."
        "\n  If unexpected, consider increasing --idle-timeout.",
    )
