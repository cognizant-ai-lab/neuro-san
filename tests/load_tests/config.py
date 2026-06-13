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
from typing import TypedDict


class TokenEntry(TypedDict):
    """Token accounting data parsed from a server log block."""

    request_id: str
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    llm_calls: int
    model: str


class ResourceSnapshot(TypedDict):
    """Point-in-time resource usage of a process."""

    rss: float
    fds: int
    threads: int
    connections: int
    children: int
    cpu: float


class ServerCounts(TypedDict):
    """Request start/finish counts from the server log."""

    primary_started: int
    primary_finished: int
    total_started: int
    total_finished: int


# Result status constants
STATUS_CREATED = "CREATED"
STATUS_FAILED = "FAILED"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_KILLED = "KILLED"

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
