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
# END COPYRIGHT

"""Shared constants, regex patterns, and defaults for the load test framework."""

import os
import re


# Result status constants
STATUS_CREATED = "CREATED"
STATUS_FAILED = "FAILED"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_KILLED = "KILLED"


# Load test levels
LEVEL_MIN = "min"
LEVEL_NORM = "norm"
LEVEL_ADV = "adv"

# Tracked retry error types.  All but ProviderRetry are neuro-san's own
# max_attempts retries; ProviderRetry counts retries the LLM provider
# SDK performs internally.
RETRY_ERROR_TYPES = [
    "RateLimitError",
    "APIError",
    "KeyError",
    "ValueError",
    "ProviderRetry",
]
# Console labels for retry types whose key alone reads poorly.
RETRY_LABELS = {
    "ProviderRetry": "Provider SDK retries",
}

# Console formatting
SEPARATOR_WIDTH = 60

# Default configuration
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
DEFAULT_STAGES = [10, 30, 50, 100]
# Parent dir of per-agent load-test hocon fixtures, relative to project root
DEFAULT_FIXTURES_HOCON_DIR: str = os.path.join("tests", "fixtures", "load_tests")
DEFAULT_TIMEOUT_SECONDS = 1200
DEFAULT_IDLE_TIMEOUT_SECONDS = 900
NETWORK_LOOKAHEAD_LINES = 10
TOKENS_PER_MILLION = 1_000_000
# Max per-request failure blocks printed to the console before the rest
# are suppressed (full detail always remains in raw_results.json).
FAILURE_LOG_LIMIT = 10
# Max length of one failed-check line in a request's failure reason;
# longer evaluator messages are cut and end with "...".
FAILURE_REASON_LINE_LIMIT = 200

# Timeouts for short-lived operations (seconds)
SOCKET_CHECK_TIMEOUT = 2
THREAD_JOIN_TIMEOUT = 2
STALE_LOG_THRESHOLD_SECONDS = 300

# Trend history: one append-only JSONL record per client run so
# throughput can be plotted over time.  The thresholds are fixed (not
# configurable) so data points stay comparable across every run.
HISTORY_FILE_NAME = "history.jsonl"
HISTORY_UNKNOWN_FILE_NAME = "history_unknown.jsonl"
HISTORY_THRESHOLDS_SECONDS = (70, 300)


# Heartbeat
HEARTBEAT_INTERVAL_SECONDS = 30

# Server log regex patterns
RETRY_LOG_PATTERN = re.compile(
    r"retrying from (RateLimit error |)(\w+)"
)
# Retries performed inside the LLM provider SDK (e.g. openai's
# "Retrying request to /chat/completions in 0.45 seconds"), which
# neuro-san never sees and so never logs as "retrying from ...".
PROVIDER_RETRY_PATTERN = re.compile(
    r"Retrying request to (\S+) in "
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
# Server "Errors detected:" event.  Logged as JSON whose "message"
# value starts with "Errors detected:" and spans literal newlines,
# ending just before the "user_id" field; matched with re.DOTALL
# against the joined log window.  Captures (message, request_id).
SERVER_ERROR_PATTERN = re.compile(
    r'"message":\s*"(Errors detected:.*?)",\s*"user_id".*?'
    r'"request_id":\s*"([^"]+)"',
    re.DOTALL,
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
