# Copyright © 2023-2026 Cognizant Technology Solutions Corp, www.cognizant.com.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""Shared constants, regex patterns, and defaults for the load test framework."""

import re
from typing import Dict
from typing import List
from typing import Optional
from typing import TypedDict


class TokenEntry(TypedDict):
    """Token accounting data parsed from a server log block."""

    request_id: str
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    llm_calls: int
    model: str


class NetworkTokenEntry(TypedDict):
    """Per-sub-network token data from a server log block."""

    request_id: str
    network: str
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    llm_calls: int
    duration: float
    model: str
    cost: float


class ValidationEvent(TypedDict):
    """Per-request validation tracking from server log."""

    request_id: str
    attempts: int
    fix_cycles: int
    errors: List[str]


class ResourceSnapshot(TypedDict):
    """Point-in-time resource usage of a process."""

    rss: float
    fds: int
    threads: int
    connections: int
    children: int
    cpu: float


class ServerCounts(TypedDict, total=False):
    """Request start/finish counts from the server log.

    All fields are optional because this dict is empty when
    no server log is available.
    """

    primary_started: int
    primary_finished: int
    total_started: int
    total_finished: int


class _RequestResultRequired(TypedDict):
    """Required fields in every request result."""

    request_id: str
    status: str
    elapsed: float
    prompt: str


class RequestResult(_RequestResultRequired, total=False):
    """Per-request result from a load test run.

    Required fields are always present.  Optional fields appear when
    token tracking is enabled or when the request fails.
    """

    error: Optional[str]
    ttft: float
    start_time: float
    end_time: float
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    llm_calls: int
    model: str
    cost_usd: float


# Result status constants
STATUS_CREATED = "CREATED"
STATUS_FAILED = "FAILED"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_KILLED = "KILLED"


class StatusCounts(TypedDict):
    """Per-status request counts from a load test stage."""

    CREATED: int
    FAILED: int
    TIMEOUT: int
    KILLED: int


class StageSummary(TypedDict, total=False):
    """Aggregate data for a single load test stage.

    All fields are optional because resource monitoring and server
    log parsing are not always enabled.
    """

    stage: int
    round: int
    concurrent: int
    counts: StatusCounts
    elapsed: float
    retries: Dict[str, int]
    total_retries: int
    amplification: float
    results: List[RequestResult]
    primary_started: Optional[int]
    primary_finished: Optional[int]
    total_started: Optional[int]
    total_finished: Optional[int]
    disconnections: List[Dict[str, str]]
    network_tokens: List[NetworkTokenEntry]
    validation_events: List[ValidationEvent]
    has_server_log: bool
    has_tokens: bool
    before_threads: Optional[int]
    after_threads: Optional[int]
    peak_threads: Optional[int]
    before_server_rss: Optional[float]
    after_server_rss: Optional[float]
    peak_server_rss: Optional[float]
    before_client_rss: Optional[float]
    after_client_rss: Optional[float]
    peak_client_rss: Optional[float]
    before_sys_mem_pct: Optional[float]
    after_sys_mem_pct: Optional[float]
    peak_sys_mem_pct: Optional[float]
    peak_sys_mem_avail_gb: Optional[float]


# Load test levels
LEVEL_MIN = "min"
LEVEL_NORM = "norm"
LEVEL_ADV = "adv"

# Tracked retry error types
RETRY_ERROR_TYPES = [
    "RateLimitError",
    "APIError",
    "KeyError",
    "ValueError",
]

# Console formatting
SEPARATOR_WIDTH = 60

# Default configuration
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
DEFAULT_STAGES = [10, 30, 50, 100]
DEFAULT_TIMEOUT_SECONDS = 1200
DEFAULT_IDLE_TIMEOUT_SECONDS = 900
NETWORK_LOOKAHEAD_LINES = 10
TOKENS_PER_MILLION = 1_000_000
# Max per-request failure blocks printed to the console before the rest
# are suppressed (full detail always remains in raw_results.json).
FAILURE_LOG_LIMIT = 10

# Timeouts for short-lived operations (seconds)
SOCKET_CHECK_TIMEOUT = 2
THREAD_JOIN_TIMEOUT = 2
PROCESS_WAIT_TIMEOUT = 10
STALE_LOG_THRESHOLD_SECONDS = 300

# Trend history: one append-only JSONL record per client run so
# throughput can be plotted over time.  The thresholds are fixed (not
# configurable) so data points stay comparable across every run.
HISTORY_FILE_NAME = "history.jsonl"
HISTORY_UNKNOWN_FILE_NAME = "history_unknown.jsonl"
HISTORY_THRESHOLDS_SECONDS = (70, 300)


class SharedRef:
    """Mutable container for passing a value between threads.

    Replaces the bare-dict pattern (e.g., ``result = {}`` /
    ``result.update(...)``), making the intent explicit and the
    expected type visible.
    """

    __slots__ = ("value",)

    def __init__(self) -> None:
        self.value = None


# Heartbeat and subprocess monitoring
HEARTBEAT_INTERVAL_SECONDS = 30
POLL_INTERVAL_SECONDS = 5.0
READ_BUFFER_SIZE = 4096

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
DONE_STREAMING_PATTERN = re.compile(
    r'Done with (\S+)\.StreamingChat'
)
VALIDATION_ATTEMPT_PATTERN = re.compile(
    r'Validating toolbox agents'
)
VALIDATION_ERROR_PATTERN = re.compile(
    r'"Validation errors: \[(.+?)\]"'
)
VALIDATION_REINVOKE_PATTERN = re.compile(
    r'Invoking agent network designer to fix the issues'
)
VALIDATION_REQUEST_ID_PATTERN = re.compile(
    r'"request_id":\s*"(request-\d+)"'
)

# Model pricing (USD per 1M tokens) — update as providers change rates
# Source: https://openai.com/api/pricing/
MODEL_PRICING = {
    "gpt-4o": {"prompt": 2.50, "completion": 10.00},
    "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
    "gpt-4.1": {"prompt": 2.00, "completion": 8.00},
    "gpt-4.1-mini": {"prompt": 0.40, "completion": 1.60},
    "gpt-4.1-nano": {"prompt": 0.10, "completion": 0.40},
    "gpt-5.2": {"prompt": 2.00, "completion": 8.00},
    "o4-mini": {"prompt": 1.10, "completion": 4.40},
}
# Fallback pricing when model is unknown
DEFAULT_PRICING = {"prompt": 2.50, "completion": 10.00}


class Formatters:
    """Reporting helpers for human-readable metrics and derived values."""

    @staticmethod
    def format_rss(rss_mb: float) -> str:
        """Format RSS in human-readable units."""
        if rss_mb >= 1024:
            return f"{rss_mb / 1024:.1f}G"
        return f"{rss_mb:.0f}M"

    @staticmethod
    def fmt_duration(seconds: float, *, precision: int = 0) -> str:
        """Format seconds with minutes suffix when >= 60s.

        Returns e.g. '1870s (31m)' or '45s' for short durations.
        """
        base = f"{seconds:.{precision}f}s"
        if seconds >= 60:
            mins = int(seconds) // 60
            return f"{base} ({mins}m)"
        return base

    @staticmethod
    def compute_amplification(
            actual_requests: int, total_retries: int,
    ) -> float:
        """Return the retry amplification factor.

        1.0 means no retries; >1.0 means some LLM calls were retried.
        """
        if actual_requests <= 0:
            return 1.0
        return (actual_requests + total_retries) / actual_requests
