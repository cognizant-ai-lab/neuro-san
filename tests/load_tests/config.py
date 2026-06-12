"""Shared constants, regex patterns, and defaults for the load test framework."""

import re


# Result status constants
STATUS_CREATED = "CREATED"
STATUS_FAILED = "FAILED"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_KILLED = "KILLED"

# Tracked retry error types
RETRY_ERROR_TYPES = [
    "RateLimitError",
    "APIError",
    "KeyError",
    "ValueError",
]

# Default configuration
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
DEFAULT_STAGES = [10, 30, 50, 100]
DEFAULT_TIMEOUT_SECONDS = 1200
DEFAULT_IDLE_TIMEOUT_SECONDS = 900

# Server log regex patterns
RETRY_LOG_PATTERN = re.compile(
    r"retrying from (RateLimit error |)(\w+)"
)
REQUEST_START_PATTERN = re.compile(
    r"Start .*/streaming_chat"
)
REQUEST_FINISH_PATTERN = re.compile(
    r"Finish .*/streaming_chat"
)
CLIENT_DISCONNECT_PATTERN = re.compile(
    r"Request handler stream closed"
)
STREAM_CLOSED_REQUEST_PATTERN = re.compile(
    r'"request_id":\s*"(request-\d+)"'
)
TASK_CANCELLED_PATTERN = re.compile(
    r"Task from ([^:]+):.*was cancelled"
)
