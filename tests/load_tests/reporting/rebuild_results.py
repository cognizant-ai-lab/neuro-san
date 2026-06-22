# Copyright (C) 2023-2026 Cognizant Technology Solutions Corp, www.cognizant.com.
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

"""Rebuild raw_results.json from individual request output files.

Useful for runs that were interrupted (Ctrl+C) before the normal
export ran.  Scans the requests/ subdirectory and log files to
reconstruct per-request results.
"""

import json
import logging
import os
import re

from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.reporting.json_metadata import JsonMetadata
from tests.load_tests.traffic.cli_builder import CliBuilder

logger = logging.getLogger(__name__)

_TIMING_RE = re.compile(
    r"Request\s+(\d+):\s+(\w+)\s+\(([0-9.]+)s",
)

_CONFIG_AGENT_RE = re.compile(
    r"Config:.*agent=([^,]+)",
)

_CONFIG_NUM_REQ_RE = re.compile(
    r"Requests:\s*(\d+)",
)


class ResultsRebuilder:
    """Reconstructs raw_results.json from per-request files."""

    def __init__(self, output_dir, *, force=False) -> None:
        self._output_dir = output_dir
        self._force = force

    def run(self) -> None:
        """Rebuild raw_results.json for one or many run directories.

        If the path contains a requests/ subdirectory, rebuild that
        single run.  Otherwise treat it as a parent directory and
        rebuild every subdirectory that has requests/ but is missing
        raw_results.json.
        """
        requests_dir = os.path.join(self._output_dir, "requests")
        json_path = os.path.join(
            self._output_dir, "raw_results.json",
        )
        if os.path.isdir(requests_dir):
            if os.path.isfile(json_path) and self._force:
                self._reclassify(json_path, requests_dir)
            else:
                self._rebuild_single()
            return
        self._rebuild_all()

    def _rebuild_all(self) -> None:
        """Scan subdirectories and rebuild or reclassify."""
        rebuilt = 0
        reclassified = 0
        skipped = 0
        for entry in sorted(os.listdir(self._output_dir)):
            sub_dir = os.path.join(self._output_dir, entry)
            if not os.path.isdir(sub_dir):
                continue
            requests_dir = os.path.join(sub_dir, "requests")
            json_path = os.path.join(sub_dir, "raw_results.json")
            if not os.path.isdir(requests_dir):
                continue
            if os.path.isfile(json_path):
                if self._force:
                    logger.info("Reclassifying: %s", entry)
                    ResultsRebuilder(
                        sub_dir, force=True,
                    ).run()
                    reclassified += 1
                else:
                    skipped += 1
                continue
            logger.info("Rebuilding: %s", entry)
            ResultsRebuilder(sub_dir).run()
            rebuilt += 1
        logger.info(
            "Done: %s rebuilt, %s reclassified, "
            "%s skipped",
            rebuilt, reclassified, skipped,
        )

    def _rebuild_single(self) -> None:
        """Rebuild raw_results.json for a single run directory."""
        requests_dir = os.path.join(self._output_dir, "requests")
        if not os.path.isdir(requests_dir):
            logger.error(
                "No requests/ directory in %s", self._output_dir,
            )
            return

        timing = self._parse_timing()
        agent, num_requests = self._parse_config()
        results = self._scan_requests(requests_dir, timing)

        if not results:
            logger.error("No request files found to rebuild.")
            return

        passed = sum(
            1 for r in results
            if r.get("status") == STATUS_CREATED
        )
        total = len(results)
        total_elapsed = max(
            r.get("elapsed", 0) for r in results
        )
        total_tokens = sum(
            r.get("total_tokens", 0) for r in results
        )
        total_cost = sum(
            r.get("cost_usd", 0.0) for r in results
        )

        raw_data = {
            "test_metadata": {
                "verdict": "REBUILT",
                "exit_code": 2,
                "note": "Reconstructed from request files",
            },
            "config": {
                "agent": agent,
                "num_requests": num_requests or total,
            },
            "aggregates": {
                "total_requests": total,
                "passed": passed,
                "failed": total - passed,
                "total_elapsed_seconds": round(
                    total_elapsed, 2,
                ),
                "avg_latency_seconds": round(
                    total_elapsed / total, 2,
                ) if total > 0 else 0,
                "total_tokens": total_tokens,
                "total_cost_usd": round(total_cost, 6),
            },
            "stage_summaries": [{
                "concurrent": total,
                "results": results,
                "elapsed": total_elapsed,
            }],
        }
        raw_data.update(JsonMetadata.build())

        json_path = os.path.join(
            self._output_dir, "raw_results.json",
        )
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(raw_data, fh, indent=2, default=str)

        logger.info(
            "Rebuilt raw_results.json: %s requests "
            "(%s passed, %s failed)",
            total, passed, total - passed,
        )
        logger.info("  Saved to: %s", json_path)

    def _parse_timing(self):
        """Extract request timing from log files."""
        timing = {}
        for filename in ("load_test.log", "progress.log"):
            path = os.path.join(self._output_dir, filename)
            if not os.path.isfile(path):
                continue
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    match = _TIMING_RE.search(line)
                    if match:
                        req_id = int(match.group(1))
                        status = match.group(2)
                        elapsed = float(match.group(3))
                        timing[req_id] = {
                            "status": status,
                            "elapsed": elapsed,
                        }
        return timing

    def _parse_config(self):
        """Extract agent name and num_requests from log."""
        agent = "unknown"
        num_requests = 0
        log_path = os.path.join(
            self._output_dir, "load_test.log",
        )
        if not os.path.isfile(log_path):
            return agent, num_requests
        with open(log_path, "r", encoding="utf-8") as fh:
            for line in fh:
                match = _CONFIG_AGENT_RE.search(line)
                if match:
                    agent = match.group(1).strip()
                match = _CONFIG_NUM_REQ_RE.search(line)
                if match:
                    num_requests = int(match.group(1))
        return agent, num_requests

    def _scan_requests(self, requests_dir, timing):
        """Parse each request stdout file into a result dict."""
        results = []
        for filename in sorted(os.listdir(requests_dir)):
            if not filename.endswith("_stdout.txt"):
                continue
            match = re.search(r"request_(\d+)_stdout", filename)
            if not match:
                continue
            req_id = int(match.group(1))
            stdout_path = os.path.join(
                requests_dir, filename,
            )
            with open(
                stdout_path, "r", encoding="utf-8",
            ) as fh:
                stdout = fh.read()

            result = self._build_result(
                req_id, stdout, timing,
            )
            results.append(result)
        return results

    @staticmethod
    def _build_result(req_id, stdout, timing):
        """Build a single result dict from stdout and timing."""
        parsed_fields = {
            "reservation_id": CliBuilder.parse_stdout_field(
                stdout, "reservation_id",
            ),
            "agent_network_name": CliBuilder.parse_stdout_field(
                stdout, "agent_network_name",
            ),
        }

        timing_info = timing.get(req_id, {})
        elapsed = timing_info.get("elapsed", 0)
        status = ResultsRebuilder._resolve_status(
            timing_info, parsed_fields,
        )

        result = {
            "request_id": f"request-{req_id}",
            "status": status,
            "elapsed": elapsed,
            "ttft": elapsed,
            "failure_reason": ResultsRebuilder._diagnose(
                status, stdout, parsed_fields,
            ),
        }
        result.update(parsed_fields)
        ResultsRebuilder._attach_tokens(result, stdout)
        return result

    @staticmethod
    def _attach_tokens(result, stdout):
        """Add token accounting fields to a result dict."""
        token_data = CliBuilder.parse_token_accounting(stdout)
        if token_data:
            result.update({
                "total_tokens": token_data.get(
                    "total_tokens", 0,
                ),
                "prompt_tokens": token_data.get(
                    "prompt_tokens", 0,
                ),
                "completion_tokens": token_data.get(
                    "completion_tokens", 0,
                ),
                "llm_calls": token_data.get(
                    "successful_requests", 0,
                ),
            })

    @staticmethod
    def _load_stdout_cache(requests_dir):
        """Load all request stdout files into a dict keyed by id."""
        cache = {}
        for filename in os.listdir(requests_dir):
            if not filename.endswith("_stdout.txt"):
                continue
            match = re.search(
                r"request_(\d+)_stdout", filename,
            )
            if not match:
                continue
            req_id = int(match.group(1))
            path = os.path.join(requests_dir, filename)
            with open(
                path, "r", encoding="utf-8",
            ) as fh:
                cache[req_id] = fh.read()
        return cache

    def _reclassify(self, json_path, requests_dir):
        """Update failure_reason and config in existing JSON."""
        with open(json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        self._fix_config(data)

        stdout_cache = ResultsRebuilder._load_stdout_cache(
            requests_dir,
        )

        updated = 0
        for stage in data.get("stage_summaries", []):
            for result in stage.get("results", []):
                if result.get("status") == STATUS_CREATED:
                    continue
                rid = result.get("request_id", "")
                match = re.search(r"(\d+)$", rid)
                if not match:
                    continue
                stdout = stdout_cache.get(
                    int(match.group(1)), "",
                )
                parsed = {
                    "reservation_id": result.get(
                        "reservation_id",
                    ),
                    "agent_network_name": result.get(
                        "agent_network_name",
                    ),
                }
                reason = ResultsRebuilder._diagnose(
                    result.get("status"), stdout, parsed,
                )
                if reason != result.get("failure_reason"):
                    result["failure_reason"] = reason
                    updated += 1

        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, default=str)
        logger.info(
            "  Updated %s failure reason(s)", updated,
        )

    def _fix_config(self, data):
        """Repair config.num_requests from log if needed."""
        _agent, num_requests = self._parse_config()
        if num_requests <= 0:
            return
        config = data.get("config", {})
        old_val = config.get("num_requests", 0)
        if old_val != num_requests:
            config["num_requests"] = num_requests
            logger.info(
                "  Fixed num_requests: %s -> %s",
                old_val, num_requests,
            )

    @staticmethod
    def _resolve_status(timing_info, parsed_fields):
        """Determine request status from log or parsed fields."""
        log_status = timing_info.get("status", "")
        if log_status == STATUS_CREATED:
            return STATUS_CREATED
        if log_status == STATUS_FAILED:
            return STATUS_FAILED
        if parsed_fields.get("reservation_id"):
            return STATUS_CREATED
        return STATUS_FAILED

    @staticmethod
    def _diagnose(status, stdout, parsed_fields):
        """Build a failure reason string for failed requests."""
        if status == STATUS_CREATED:
            return None
        reasons = []
        for field in ("reservation_id", "agent_network_name"):
            if not parsed_fields.get(field):
                reasons.append(f"missing {field}")
        tokens = CliBuilder.parse_token_accounting(stdout)
        if not tokens:
            reasons.append("no token data")
        else:
            empty = tokens.get("empty_responses", 0)
            completion = tokens.get("completion_tokens", 0)
            if empty > 0:
                reasons.append(
                    f"empty LLM response "
                    f"({completion} completion tokens, "
                    f"{empty} empty response(s))"
                )
            else:
                reasons.append("incomplete response")
        return "; ".join(reasons) if reasons else None
