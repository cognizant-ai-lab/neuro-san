"""Resource reporting — server and client resource delta analysis."""

import logging
from typing import Tuple

from tests.load_tests.reporting.table_utils import log_table

logger = logging.getLogger(__name__)


def build_resource_row(stage_label, before, after) -> Tuple:
    """Build a resource summary row from before/after snapshots."""
    rss_delta = after.get("rss") - before.get("rss")
    thread_delta = after.get("threads") - before.get("threads")
    return (
        str(stage_label),
        f"{before.get('rss'):.1f}M",
        f"{after.get('rss'):.1f}M",
        f"+{rss_delta:.1f}M",
        str(after.get("fds")),
        f"{before.get('threads')} -> {after.get('threads')}",
        f"+{thread_delta}",
        str(after.get("connections")),
        f"{after.get('cpu'):.1f}%",
        str(after.get("children")),
    )


def build_client_row(stage_label, before, peak, settled) -> Tuple:
    """Build a client resource row from before/peak/settled snapshots."""
    rss_delta = settled.get("rss") - before.get("rss")
    peak_rss = f"{peak.get('rss'):.1f}M" if peak else "-"
    return (
        str(stage_label),
        f"{before.get('rss'):.1f}M",
        peak_rss,
        f"{settled.get('rss'):.1f}M",
        f"{rss_delta:+.1f}M",
        f"{settled.get('cpu'):.1f}%",
        str(settled.get("fds")),
        str(settled.get("threads")),
    )


def log_resource_analysis(resource_rows, total_client_reqs, total_server_calls):
    """Log server resource analysis table."""
    if not resource_rows:
        return
    resource_header = [
        "Concurrent", "Before RSS", "Settled RSS", "RSS Delta",
        "FDs", "Threads", "Thread Delta",
        "Conns", "CPU%", "Children",
    ]
    logger.info("\n%s", "=" * 60)
    if total_server_calls > 0:
        logger.info(
            "  SERVER RESOURCE ANALYSIS"
            " (%s client requests, %s server calls)",
            total_client_reqs, total_server_calls,
        )
    else:
        logger.info(
            "  SERVER RESOURCE ANALYSIS"
            " (%s total requests)",
            total_client_reqs,
        )
    logger.info("=" * 60)
    log_table(resource_header, resource_rows)
    log_resource_deltas(resource_rows)


def log_resource_deltas(resource_rows):
    """Log overall resource deltas if enough data points."""
    if len(resource_rows) < 2:
        return
    first = resource_rows[0]
    last = resource_rows[-1]
    logger.info("\n  Server overall deltas (first stage vs last stage):")
    logger.info(
        "    RSS:         +%.1f MB",
        float(last[2].rstrip("M")) - float(first[1].rstrip("M")),
    )
    logger.info(
        "    FDs:         +%s",
        int(last[4]) - int(first[4]),
    )
    logger.info(
        "    Threads:     +%s",
        int(last[5].split(" -> ")[1]) - int(first[5].split(" -> ")[0]),
    )
    logger.info(
        "    Connections: +%s",
        int(last[7]) - int(first[7]),
    )
    logger.info(
        "    Children:    +%s",
        int(last[9]) - int(first[9]),
    )


def log_client_analysis(client_rows, total_client_reqs):
    """Log client resource analysis table."""
    if not client_rows:
        return
    client_header = [
        "Concurrent", "Before RSS", "Peak RSS",
        "Settled RSS", "RSS Delta",
        "CPU%", "FDs", "Threads",
    ]
    logger.info("\n%s", "=" * 60)
    logger.info(
        "  CLIENT RESOURCE ANALYSIS"
        " (%s total requests)",
        total_client_reqs,
    )
    logger.info("=" * 60)
    log_table(client_header, client_rows)
    log_client_deltas(client_rows)


def log_client_deltas(client_rows):
    """Log overall client resource deltas if enough data points."""
    if len(client_rows) < 2:
        return
    first = client_rows[0]
    last = client_rows[-1]
    logger.info("\n  Client overall deltas (first stage vs last stage):")
    logger.info(
        "    RSS:     +%.1f MB",
        float(last[3].rstrip("M")) - float(first[1].rstrip("M")),
    )
    logger.info(
        "    FDs:     +%s",
        int(last[6]) - int(first[6]),
    )
    logger.info(
        "    Threads: +%s",
        int(last[7]) - int(first[7]),
    )
