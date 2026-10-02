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

"""Rebuild raw_results.json from individual request output files.

Useful for runs that were interrupted (Ctrl+C) before the normal
export ran.  Scans the requests/ subdirectory and log files to
reconstruct per-request results.
"""

import json
import logging
import os
import re
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_KILLED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.reporting.json_metadata import JsonMetadata
from tests.load_tests.traffic.output_parser import OutputParser

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

    def __init__(self, output_dir: str, force: bool = False) -> None:
        """
        Constructor.

        :param output_dir: Run output directory, or a parent directory holding many runs
        :param force: True to reclassify failures in runs that already have raw_results.json
        """
        self._output_dir = output_dir
        self._force = force

    def run(self) -> None:
        """Rebuild raw_results.json for one or many run directories.

        If the path contains a requests/ subdirectory, rebuild that
        single run.  Otherwise treat it as a parent directory and
        rebuild every subdirectory that has requests/ but is missing
        raw_results.json.
        """
        requests_dir: str = os.path.join(self._output_dir, "requests")
        json_path: str = os.path.join(
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
        rebuilt: int = 0
        reclassified: int = 0
        skipped: int = 0
        for entry in sorted(os.listdir(self._output_dir)):
            sub_dir: str = os.path.join(self._output_dir, entry)
            if not os.path.isdir(sub_dir):
                continue
            requests_dir: str = os.path.join(sub_dir, "requests")
            json_path: str = os.path.join(sub_dir, "raw_results.json")
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
        requests_dir: str = os.path.join(self._output_dir, "requests")
        if not os.path.isdir(requests_dir):
            logger.error(
                "No requests/ directory in %s", self._output_dir,
            )
            return

        timing: Dict[int, Dict[str, Any]] = self._parse_timing()
        agent: str
        num_requests: int
        agent, num_requests = self._parse_config()
        results: List[Dict[str, Any]] = self._scan_requests(requests_dir, timing)

        if not results:
            logger.error("No request files found to rebuild.")
            return

        passed: int = sum(
            1 for r in results
            if r.get("status") == STATUS_CREATED
        )
        total: int = len(results)
        # The slowest request stands in for the run's wall-clock time,
        # which is not recoverable from per-request files alone.
        total_elapsed: float = max(
            r.get("elapsed", 0) for r in results
        )
        avg_latency: float = sum(
            r.get("elapsed", 0) for r in results
        ) / total if total > 0 else 0
        total_tokens: int = sum(
            r.get("total_tokens", 0) for r in results
        )
        total_cost: float = sum(
            r.get("cost_usd", 0.0) for r in results
        )

        raw_data: Dict[str, Any] = {
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
                "avg_latency_seconds": round(avg_latency, 2),
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

        json_path: str = os.path.join(
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

    def _parse_timing(self) -> Dict[int, Dict[str, Any]]:
        """
        Extract request timing from log files.

        :return: Request id to its status and elapsed seconds, from load_test.log and progress.log
        """
        timing: Dict[int, Dict[str, Any]] = {}
        for filename in ("load_test.log", "progress.log"):
            path: str = os.path.join(self._output_dir, filename)
            if not os.path.isfile(path):
                continue
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    match: Optional[re.Match] = _TIMING_RE.search(line)
                    if match:
                        req_id: int = int(match.group(1))
                        status: str = match.group(2)
                        elapsed: float = float(match.group(3))
                        timing[req_id] = {
                            "status": status,
                            "elapsed": elapsed,
                        }
        return timing

    def _parse_config(self) -> Tuple[str, int]:
        """
        Extract agent name and num_requests from log.

        :return: (agent, num_requests); ("unknown", 0) when load_test.log is missing or has no config lines
        """
        agent: str = "unknown"
        num_requests: int = 0
        log_path: str = os.path.join(
            self._output_dir, "load_test.log",
        )
        if not os.path.isfile(log_path):
            return agent, num_requests
        with open(log_path, "r", encoding="utf-8") as fh:
            for line in fh:
                match: Optional[re.Match] = _CONFIG_AGENT_RE.search(line)
                if match:
                    agent = match.group(1).strip()
                match = _CONFIG_NUM_REQ_RE.search(line)
                if match:
                    num_requests = int(match.group(1))
        return agent, num_requests

    def _scan_requests(self, requests_dir: str, timing: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Parse each request stdout file into a result dict.

        :param requests_dir: Directory holding the request_<id>_stdout.txt files
        :param timing: Request timing from _parse_timing
        :return: One result dict per stdout file, in file name order
        """
        results: List[Dict[str, Any]] = []
        for filename in sorted(os.listdir(requests_dir)):
            if not filename.endswith("_stdout.txt"):
                continue
            match: Optional[re.Match] = re.search(r"request_(\d+)_stdout", filename)
            if not match:
                continue
            req_id: int = int(match.group(1))
            stdout_path: str = os.path.join(
                requests_dir, filename,
            )
            stdout: str
            with open(
                stdout_path, "r", encoding="utf-8",
            ) as fh:
                stdout = fh.read()

            result: Dict[str, Any] = self._build_result(
                req_id, stdout, timing,
            )
            results.append(result)
        return results

    @staticmethod
    def _build_result(req_id: int, stdout: str, timing: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Build a single result dict from stdout and timing.

        :param req_id: Numeric request id
        :param stdout: Contents of the request's stdout file
        :param timing: Request timing from _parse_timing
        :return: The result dict for the request
        """
        parsed_fields: Dict[str, Optional[str]] = {
            "reservation_id": OutputParser.parse_stdout_field(
                stdout, "reservation_id",
            ),
            "agent_network_name": OutputParser.parse_stdout_field(
                stdout, "agent_network_name",
            ),
        }

        timing_info: Dict[str, Any] = timing.get(req_id, {})
        elapsed: float = timing_info.get("elapsed", 0)
        status: str = ResultsRebuilder._resolve_status(timing_info)

        result: Dict[str, Any] = {
            "request_id": f"request-{req_id}",
            "status": status,
            "elapsed": elapsed,
            "time_to_first_response": 0,
            "failure_reason": ResultsRebuilder._diagnose(
                status, stdout, parsed_fields,
            ),
        }
        result.update(parsed_fields)
        ResultsRebuilder._attach_tokens(result, stdout)
        return result

    @staticmethod
    def _attach_tokens(result: Dict[str, Any], stdout: str) -> None:
        """
        Add token accounting fields to a result dict.

        :param result: Result dict, updated in place
        :param stdout: Contents of the request's stdout file
        """
        token_data: Dict[str, Any] = OutputParser.parse_token_accounting(stdout)
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
    def _load_stdout_cache(requests_dir: str) -> Dict[int, str]:
        """
        Load all request stdout files into a dict keyed by id.

        :param requests_dir: Directory holding the request_<id>_stdout.txt files
        :return: Request id to the contents of its stdout file
        """
        cache: Dict[int, str] = {}
        for filename in os.listdir(requests_dir):
            if not filename.endswith("_stdout.txt"):
                continue
            match: Optional[re.Match] = re.search(
                r"request_(\d+)_stdout", filename,
            )
            if not match:
                continue
            req_id: int = int(match.group(1))
            path: str = os.path.join(requests_dir, filename)
            with open(
                path, "r", encoding="utf-8",
            ) as fh:
                cache[req_id] = fh.read()
        return cache

    def _reclassify(self, json_path: str, requests_dir: str) -> None:
        """
        Update failure_reason and config in existing JSON.

        :param json_path: Path to raw_results.json, rewritten in place
        :param requests_dir: Directory holding the request_<id>_stdout.txt files
        """
        data: Dict[str, Any]
        with open(json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        self._fix_config(data)

        stdout_cache: Dict[int, str] = ResultsRebuilder._load_stdout_cache(
            requests_dir,
        )

        updated: int = 0
        for stage in data.get("stage_summaries", []):
            for result in stage.get("results", []):
                if result.get("status") == STATUS_CREATED:
                    continue
                rid: str = result.get("request_id", "")
                match: Optional[re.Match] = re.search(r"(\d+)$", rid)
                if not match:
                    continue
                stdout: str = stdout_cache.get(
                    int(match.group(1)), "",
                )
                parsed: Dict[str, Optional[str]] = {
                    "reservation_id": result.get(
                        "reservation_id",
                    ),
                    "agent_network_name": result.get(
                        "agent_network_name",
                    ),
                }
                reason: Optional[str] = ResultsRebuilder._diagnose(
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

    def _fix_config(self, data: Dict[str, Any]) -> None:
        """
        Repair config.num_requests from log if needed.

        :param data: Parsed raw_results.json, updated in place
        """
        _agent: str
        num_requests: int
        _agent, num_requests = self._parse_config()
        if num_requests <= 0:
            return
        config: Dict[str, Any] = data.get("config", {})
        old_val: int = config.get("num_requests", 0)
        if old_val != num_requests:
            config["num_requests"] = num_requests
            logger.info(
                "  Fixed num_requests: %s -> %s",
                old_val, num_requests,
            )

    @staticmethod
    def _resolve_status(timing_info: Dict[str, Any]) -> str:
        """Determine request status from the log line for the request.

        Every status the runner reports is preserved, including TIMEOUT
        and KILLED: a rebuild that collapsed those into CREATED or
        FAILED would misstate what happened.  A request with no log
        line was never observed to finish -- failures past
        FAILURE_LOG_LIMIT are never printed -- so it counts as failed
        rather than being guessed at from its partial output.

        :param timing_info: The request's entry from _parse_timing; empty when it has no log line
        :return: The status from the log line, or FAILED when there is none
        """
        log_status: str = timing_info.get("status", "")
        if log_status in (
            STATUS_CREATED, STATUS_FAILED, STATUS_TIMEOUT, STATUS_KILLED,
        ):
            return log_status
        return STATUS_FAILED

    @staticmethod
    def _diagnose(status: str, stdout: str, parsed_fields: Dict[str, Optional[str]]) -> Optional[str]:
        """
        Build a failure reason string for failed requests.

        :param status: The request's status
        :param stdout: Contents of the request's stdout file
        :param parsed_fields: reservation_id and agent_network_name parsed from stdout; None when missing
        :return: Reasons joined by "; ", or None for a CREATED request
        """
        if status == STATUS_CREATED:
            return None
        reasons: List[str] = []
        for field in ("reservation_id", "agent_network_name"):
            if not parsed_fields.get(field):
                reasons.append(f"missing {field}")
        tokens: Dict[str, Any] = OutputParser.parse_token_accounting(stdout)
        if not tokens:
            reasons.append("no token data")
        else:
            empty: int = tokens.get("empty_responses", 0)
            completion: int = tokens.get("completion_tokens", 0)
            if empty > 0:
                reasons.append(
                    f"empty LLM response "
                    f"({completion} completion tokens, "
                    f"{empty} empty response(s))"
                )
            else:
                reasons.append("incomplete response")
        return "; ".join(reasons) if reasons else None
