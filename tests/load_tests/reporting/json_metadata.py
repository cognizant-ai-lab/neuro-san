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

"""Self-documenting metadata for raw_results.json.

Provides field descriptions, health thresholds, analysis hints, and
unit labels so that any LLM can interpret the JSON without external
documentation.
"""

from typing import Dict
from typing import List


class JsonMetadata:
    """Builds the _schema, _thresholds, _analysis_hints, and _units
    sections embedded in raw_results.json."""

    @staticmethod
    def schema() -> Dict[str, str]:
        """Return field descriptions for every non-obvious JSON field."""
        return {
            "test_metadata.timestamp":
                "ISO 8601 test start time with timezone.",
            "test_metadata.neuro_san_version":
                "Installed neuro-san package version, or null.",
            "test_metadata.neuro_san_studio_version":
                "Installed neuro-san-studio package version, or null.",
            "test_metadata.verdict":
                "PASSED if all requests succeeded, FAILED otherwise.",
            "config.level":
                "Test depth: min (traffic only), norm (+resources), "
                "adv (+tokens, JSON, pool analysis).",
            "config.mode":
                "flat = same concurrency every stage; "
                "ramp = increasing concurrency per stage.",
            "config.same_prompt":
                "If true, all requests use the same prompt "
                "(collision stress test).",
            "aggregates.total_elapsed_seconds":
                "Sum of wall-clock time across all stages.",
            "aggregates.avg_latency_seconds":
                "Total elapsed / total requests.",
            "stage_summaries[].counts":
                "Per-status request counts: "
                "CREATED=success, FAILED=error/crash, "
                "TIMEOUT=hit hard timeout cap, "
                "KILLED=no output for idle_timeout.",
            "stage_summaries[].retries":
                "Server-side max_attempts retries by error type "
                "(e.g. RateLimitError, APIError). "
                "Empty dict means zero retries.",
            "stage_summaries[].amplification":
                "Ratio of total server LLM attempts to client "
                "requests. 1.0 = no retries. "
                ">1.0 means some requests were retried.",
            "stage_summaries[].disconnections":
                "Client disconnections: list of "
                "{request_id, agent} for requests where the "
                "client disconnected before the server finished.",
            "stage_summaries[].primary_started":
                "Server-side count of requests received for the "
                "target agent network.",
            "stage_summaries[].primary_finished":
                "Server-side count of requests completed for the "
                "target agent network.",
            "stage_summaries[].total_started":
                "Total server calls started (includes sub-network "
                "calls for multi-agent networks).",
            "stage_summaries[].total_finished":
                "Total server calls completed.",
            "stage_summaries[].before_threads":
                "Server thread count before stage execution.",
            "stage_summaries[].after_threads":
                "Server thread count after settle period.",
            "stage_summaries[].peak_threads":
                "Peak server thread count during stage execution "
                "(only present when heartbeat captured it).",
            "results[].status":
                "CREATED=success, FAILED=error/crash, "
                "TIMEOUT=exceeded request timeout, "
                "KILLED=no output for idle_timeout.",
            "results[].error":
                "Error message string when status != CREATED, "
                "null on success.",
            "results[].total_tokens":
                "Total LLM tokens (prompt + completion) for "
                "this request.",
            "results[].cost_usd":
                "Estimated OpenAI API cost for this request.",
            "network_tokens[].network":
                "Sub-agent network name. For multi-agent systems "
                "(e.g. AND), each sub-network appears separately.",
            "network_tokens[].duration":
                "Server-side LLM processing time for this "
                "sub-network (excludes client overhead).",
            "network_tokens[].cost":
                "Server-side cost for this sub-network.",
            "resource_rows[].before":
                "Server process snapshot before stage execution.",
            "resource_rows[].after":
                "Server process snapshot after settle period.",
            "resource_rows[].*.rss":
                "Resident Set Size in megabytes.",
            "resource_rows[].*.fds":
                "Open file descriptor count.",
            "resource_rows[].*.threads":
                "OS thread count for the server process.",
            "resource_rows[].*.connections":
                "Active network connections.",
            "resource_rows[].*.children":
                "Child process count.",
            "resource_rows[].*.cpu":
                "CPU usage percentage.",
            "client_resource_rows[].before":
                "Client process snapshot before stage.",
            "client_resource_rows[].peak":
                "Client process peak snapshot during stage.",
            "client_resource_rows[].settled":
                "Client process snapshot after all subprocesses "
                "completed.",
            "config.request_timeout":
                "Hard timeout per request in seconds. "
                "Kills the request if it exceeds this limit.",
            "config.idle_timeout":
                "Per-request idle timeout in seconds. "
                "Kills a request if agent_cli produces no "
                "stdout/stderr output for this duration. "
                "Resets on every output activity.",
            "config.stage_timeout":
                "Hard timeout for an entire stage/round in "
                "seconds. Kills all remaining in-flight "
                "requests when the stage exceeds this limit.",
            "config.total_timeout":
                "Hard timeout for the entire load test in "
                "seconds. 0 means disabled.",
            "config.settle_time":
                "Seconds to wait after each stage for server "
                "cleanup before taking the post-stage resource "
                "snapshot.",
        }

    @staticmethod
    def thresholds() -> Dict[str, object]:
        """Return health thresholds for automated analysis."""
        return {
            "amplification_warning": 1.2,
            "amplification_critical": 1.5,
            "failure_pct_warning": 1.0,
            "failure_pct_critical": 5.0,
            "timeout_pct_warning": 1.0,
            "timeout_pct_critical": 5.0,
            "retry_pct_warning": 5.0,
            "retry_pct_critical": 20.0,
            "thread_growth_per_round_warning": 10,
            "thread_growth_per_round_critical": 50,
            "rss_growth_per_round_mb_warning": 50,
            "rss_growth_per_round_mb_critical": 200,
            "pool_reuse_pct_healthy": 80,
            "pool_reuse_pct_warning": 50,
            "duration_degradation_pct_warning": 15,
            "cost_outlier_multiplier": 2.0,
        }

    @staticmethod
    def analysis_hints() -> List[str]:
        """Return diagnostic patterns to check."""
        return [
            "Compare thread counts across rounds — growth "
            "without reclaiming suggests a thread leak.",
            "Compare RSS across rounds — growth without "
            "reclaiming suggests a memory leak.",
            "Compare pool reuse % vs pool available — low "
            "reuse with high availability suggests executor "
            "pool lock contention.",
            "Check if avg duration increases across rounds "
            "at the same concurrency — indicates resource "
            "pressure or degradation.",
            "Check completion_tokens variance across "
            "requests — high variance means LLM behavior "
            "is unpredictable and cost estimates unreliable.",
            "Compare primary_started/finished vs expected "
            "request count — mismatch suggests server-side "
            "request routing issues.",
            "Check amplification factor — values above 1.0 "
            "mean the server retried LLM calls, increasing "
            "cost and latency.",
            "Check for TIMEOUT or KILLED requests — these "
            "indicate the server or LLM is too slow for the "
            "configured timeout thresholds.",
            "Compare client-side elapsed vs server-side "
            "network_tokens duration — large gaps indicate "
            "client overhead (subprocess, gRPC, CLI parsing).",
            "Check FD growth across rounds — unclosed file "
            "descriptors indicate resource leaks.",
        ]

    @staticmethod
    def units() -> Dict[str, str]:
        """Return unit labels for numeric fields."""
        return {
            "elapsed": "seconds",
            "duration": "seconds",
            "total_elapsed_seconds": "seconds",
            "avg_latency_seconds": "seconds",
            "request_timeout": "seconds",
            "idle_timeout": "seconds",
            "stage_timeout": "seconds",
            "total_timeout": "seconds",
            "settle_time": "seconds",
            "rss": "megabytes",
            "cpu": "percent",
            "cost_usd": "USD",
            "cost": "USD",
            "total_cost_usd": "USD",
            "total_tokens": "tokens",
            "prompt_tokens": "tokens",
            "completion_tokens": "tokens",
            "estimated_tokens_per_request": "tokens",
        }

    @staticmethod
    def reporting_instructions() -> str:
        """Return instructions for LLM-based analysis."""
        return (
            "Report ALL checks explicitly, including clean "
            "results (e.g. '0 errors found', '0 retries', "
            "'no thread growth'). Do not skip checks with "
            "zero or normal values — explicitly confirming "
            "that something is healthy is as important as "
            "flagging issues. For each check in "
            "_analysis_hints, state the finding and rate it "
            "as OK, WARNING, or CRITICAL using _thresholds."
        )

    @staticmethod
    def build() -> Dict[str, object]:
        """Return the complete metadata block for raw_results.json."""
        return {
            "_schema": JsonMetadata.schema(),
            "_thresholds": JsonMetadata.thresholds(),
            "_analysis_hints": JsonMetadata.analysis_hints(),
            "_units": JsonMetadata.units(),
            "_reporting_instructions": (
                JsonMetadata.reporting_instructions()
            ),
        }
