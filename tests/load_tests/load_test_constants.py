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

# Whole re module: "from re import compile" would hide the builtin compile().
import re
from os.path import join
from typing import Dict
from typing import List
from typing import Set


class LoadTestConstants:
    """
    Shared constants, regex patterns, and defaults for the load test framework.
    """

    # Result status constants
    STATUS_CREATED: str = "CREATED"
    STATUS_FAILED: str = "FAILED"
    STATUS_TIMEOUT: str = "TIMEOUT"
    STATUS_KILLED: str = "KILLED"

    # Load test levels
    LEVEL_MIN: str = "min"
    LEVEL_NORM: str = "norm"
    LEVEL_ADV: str = "adv"

    # Flat-mode defaults for --level adv, unless the flag is given
    ADV_NUM_REQUESTS: int = 50
    ADV_NUM_ROUNDS: int = 3

    # Tracked retry error types.  All but ProviderRetry are neuro-san's own
    # max_attempts retries; ProviderRetry counts retries the LLM provider
    # SDK performs internally.
    RETRY_ERROR_TYPES: List[str] = ["RateLimitError", "APIError", "KeyError", "ValueError", "ProviderRetry"]
    # Console labels for retry types whose key alone reads poorly.
    RETRY_LABELS: Dict[str, str] = {"ProviderRetry": "Provider SDK retries"}

    # Default configuration
    LOCAL_HOSTS: Set[str] = {"localhost", "127.0.0.1", "::1"}
    # Server port when --https is set and --port is not given
    DEFAULT_HTTPS_PORT: int = 443
    DEFAULT_STAGES: List[int] = [10, 30, 50, 100]
    # Parent dir of per-agent load-test hocon fixtures, relative to project root
    DEFAULT_FIXTURES_HOCON_DIR: str = join("tests", "fixtures", "load_tests")
    DEFAULT_TIMEOUT_SECONDS: int = 1200
    DEFAULT_IDLE_TIMEOUT_SECONDS: int = 900
    DEFAULT_STAGE_TIMEOUT_SECONDS: int = 1500
    DEFAULT_SETTLE_TIME_SECONDS: int = 15
    NETWORK_LOOKAHEAD_LINES: int = 10
    # Max per-request failure blocks printed to the console before the rest
    # are suppressed (full detail always remains in raw_results.json).
    FAILURE_LOG_LIMIT: int = 10
    # Max length of one failed-check line in a request's failure reason;
    # longer evaluator messages are cut and end with "...".
    FAILURE_REASON_LINE_LIMIT: int = 200

    # Timeouts for short-lived operations (seconds)
    SOCKET_CHECK_TIMEOUT_SECONDS: int = 2
    THREAD_JOIN_TIMEOUT_SECONDS: int = 2
    STALE_LOG_THRESHOLD_SECONDS: int = 300

    # Trend history: one append-only JSONL record per client run so
    # throughput can be plotted over time.  The thresholds are fixed (not
    # configurable) so data points stay comparable across every run.
    HISTORY_FILE_NAME: str = "history.jsonl"
    HISTORY_UNKNOWN_FILE_NAME: str = "history_unknown.jsonl"
    HISTORY_SHORT_THRESHOLD_SECONDS: int = 70
    HISTORY_LONG_THRESHOLD_SECONDS: int = 300
    # Both thresholds, shortest first: the order of the history columns.
    HISTORY_THRESHOLDS_SECONDS: List[int] = [HISTORY_SHORT_THRESHOLD_SECONDS, HISTORY_LONG_THRESHOLD_SECONDS]

    # Where the client token counts come from, as printed in the token usage lines.
    CLIENT_TOKEN_SOURCE: str = "HTTP token_accounting"

    # Files in each run directory. LEGACY_RUN_LOG_FILE_NAME is the other run log name the rebuild reads.
    RAW_RESULTS_FILE_NAME: str = "raw_results.json"
    PROGRESS_LOG_FILE_NAME: str = "progress.log"
    SERVER_TOKENS_LOG_FILE_NAME: str = "server_tokens.log"
    STDOUT_LOG_FILE_NAME: str = "stdout.log"
    # End of each request's stdout file name in the requests folder: request_<id>_stdout.txt.
    REQUEST_STDOUT_FILE_SUFFIX: str = "_stdout.txt"
    LEGACY_RUN_LOG_FILE_NAME: str = "load_test.log"
    # Folder in each run directory with one stdout (and stderr) file per request.
    REQUESTS_DIR_NAME: str = "requests"

    # Heartbeat
    HEARTBEAT_INTERVAL_SECONDS: int = 30

    # Server log regex patterns
    # RunContextRunnable.journal_retry_reason() warning "Retrying: <reason> (<ErrorType>) - <error>" before each
    # max_attempts retry. Group 1 is the error type, e.g. "RateLimitError".
    RETRY_LOG_PATTERN: re.Pattern = re.compile(r"Retrying: .*? \((\w+)\) - ")
    # Retries performed inside the LLM provider SDK (e.g. openai's
    # "Retrying request to /chat/completions in 0.45 seconds"), which
    # neuro-san never sees and so never logs as "Retrying: ...".
    PROVIDER_RETRY_PATTERN: re.Pattern = re.compile(r"Retrying request to (\S+) in ")
    # HttpServerApp "[<instance>] Start <agent>/streaming_chat" when a streaming chat request starts.
    # Group 1 is the agent name, e.g. "hello_world".
    REQUEST_START_PATTERN: re.Pattern = re.compile(r"Start (.*)/streaming_chat")
    # HttpServerApp "[<instance>] Finish <agent>/streaming_chat" when that request ends. No groups.
    REQUEST_FINISH_PATTERN: re.Pattern = re.compile(r"Finish .*/streaming_chat")
    # StreamingChatHandler "Request handler stream closed." when the client stream closes. No groups.
    CLIENT_DISCONNECT_PATTERN: re.Pattern = re.compile(r"Request handler stream closed")
    # The "request_id" field of a JSON server log line, to tie the line to its request.
    # Group 1 is the request id, e.g. "request-3".
    REQUEST_ID_PATTERN: re.Pattern = re.compile(r'"request_id":\s*"(request-\d+)"')
    # leaf-common AsyncioExecutor "Task from <submitter_id>:<function> was cancelled". Group 1 is the
    # submitter id; for a session's streaming_chat task that is its request id, e.g. "request-3".
    TASK_CANCELLED_PATTERN: re.Pattern = re.compile(r"Task from ([^:]+):.*was cancelled")
    # AsyncAgentService "Done with <agent>.StreamingChat request for ...". Group 1 is the agent name.
    DONE_STREAMING_PATTERN: re.Pattern = re.compile(r'Done with (\S+)\.StreamingChat')
    # ToolboxNetworkValidator "Validating toolbox agents..." at each validation attempt. No groups.
    VALIDATION_ATTEMPT_PATTERN: re.Pattern = re.compile(r'Validating toolbox agents')
    # neuro-san-studio AgentNetworkPersistenceMiddleware warning "Validation errors: %s" with a Python list of
    # strings, as the JSON "message" value. Group 1 is the list text with its brackets, e.g. "['Missing front man']".
    VALIDATION_ERROR_PATTERN: re.Pattern = re.compile(r'"Validation errors: (\[.*\])"')
    # One error in the VALIDATION_ERROR_PATTERN list text. Python writes each error in single quotes, or in double
    # quotes when it holds a single quote. Group 1 is a single-quoted error, group 2 a double-quoted one.
    VALIDATION_ERROR_ITEM_PATTERN: re.Pattern = re.compile(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"")
    # Agent network designer warning "Invoking agent network designer to fix the issues (attempt n/m)."
    # at each fix cycle. No groups.
    VALIDATION_REINVOKE_PATTERN: re.Pattern = re.compile(r'Invoking agent network designer to fix the issues')
    # Server "Errors detected:" event.  Logged as JSON whose "message"
    # value starts with "Errors detected:" and spans literal newlines,
    # ending just before the "user_id" field; matched with re.DOTALL
    # against the joined log window.  Captures (message, request_id).
    SERVER_ERROR_PATTERN: re.Pattern = re.compile(
        r'"message":\s*"(Errors detected:.*?)",\s*"user_id".*?'
        r'"request_id":\s*"([^"]+)"',
        re.DOTALL,
    )
