"""Resource monitoring — psutil-based process snapshots.

Interim implementation. May be replaced by neuro-san built-in
monitoring and telemetry when those features become available.
"""

import logging
from typing import Any
from typing import Dict
from typing import Optional

import psutil

logger = logging.getLogger(__name__)


def find_process(keyword) -> Optional[psutil.Process]:
    """Find a running process whose command line contains the given keyword."""
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if keyword in cmdline:
                return psutil.Process(proc.info.get("pid"))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def find_process_by_port(port) -> Optional[psutil.Process]:
    """Find a process listening on the given port."""
    for proc in psutil.process_iter(["pid"]):
        try:
            for conn in proc.net_connections():
                if conn.status == "LISTEN" and conn.laddr.port == port:
                    return psutil.Process(proc.info.get("pid"))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def snapshot(proc) -> Optional[Dict[str, Any]]:
    """Capture a point-in-time resource snapshot of a process."""
    try:
        mem = proc.memory_info()
        return {
            "rss": mem.rss / 1024 / 1024,
            "fds": proc.num_fds(),
            "threads": proc.num_threads(),
            "connections": len(proc.net_connections()),
            "children": len(proc.children()),
            "cpu": proc.cpu_percent(interval=0.1),
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def log_snapshot(label, snap):
    """Log a single resource snapshot."""
    if snap is None:
        logger.info("  %s: process not found", label)
        return
    logger.info(
        "  %s: RSS=%.1f MB, FDs=%s, Threads=%s, Conns=%s, CPU=%.1f%%, Children=%s",
        label, snap.get("rss"), snap.get("fds"), snap.get("threads"),
        snap.get("connections"), snap.get("cpu"), snap.get("children"),
    )
