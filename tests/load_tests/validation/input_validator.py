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

"""Validates and resolves user input for load test configuration.

Handles stage resolution, max-request capping, and the interactive
cost-confirmation flow that fires a single probe request to measure
actual token usage before committing to a full run.
"""

import logging
import os
import resource
import sys
from typing import List
from typing import Optional
from typing import Tuple

import psutil

from tests.load_tests.config import DEFAULT_STAGES
from tests.load_tests.config import LEVEL_ADV
from tests.load_tests.config import RequestResult
from tests.load_tests.config import SEPARATOR_WIDTH

logger = logging.getLogger(__name__)


class InputValidator:
    """Validates and resolves user input for load test configuration.

    Holds the parsed CLI args so that callers do not need to pass
    them to every method.
    """

    def __init__(self, args) -> None:
        self._args = args

    def validate_agent_name(self) -> None:
        """Reject --agent values that look like filesystem paths.

        The server resolves agents by registry-relative name
        (e.g. 'basic/hello_world'), not by absolute path.
        """
        agent = self._args.agent
        if os.path.isabs(agent):
            logger.error(
                "ERROR: --agent appears to be a filesystem path:\n"
                "  %s\n\n"
                "Use the registry-relative name instead.\n"
                "For example, if the agent HOCON is at:\n"
                "  registries/basic/hello_world.hocon\n"
                "Then use:\n"
                "  --agent basic/hello_world",
                agent,
            )
            sys.exit(1)

    def resolve_stages(self) -> List[int]:
        """Return the list of concurrency stages to run.

        If --ramp is set and --stages provided, parse the CSV.
        If --ramp is set without --stages, use DEFAULT_STAGES.
        Otherwise return a single-stage list from --num-requests.
        """
        if self._args.ramp:
            if self._args.stages is not None:
                try:
                    stages = [
                        int(s.strip())
                        for s in self._args.stages.split(",")
                        if s.strip()
                    ]
                except ValueError:
                    logger.error(
                        "--stages must be comma-separated integers "
                        "(e.g. 3,10,30). Got: '%s'",
                        self._args.stages,
                    )
                    sys.exit(1)
                if not stages or any(s <= 0 for s in stages):
                    logger.error(
                        "--stages values must be positive integers. "
                        "Got: '%s'",
                        self._args.stages,
                    )
                    sys.exit(1)
                return stages
            return list(DEFAULT_STAGES)
        if self._args.num_requests <= 0:
            logger.error(
                "--num-requests must be a positive integer. Got: %s",
                self._args.num_requests,
            )
            sys.exit(1)
        return [self._args.num_requests]

    def resolve_max_requests(self, stages) -> int:
        """Return the effective max-requests cap."""
        if self._args.max_requests is not None:
            if self._args.max_requests <= 0:
                logger.error(
                    "--max-requests must be a positive integer. Got: %s",
                    self._args.max_requests,
                )
                sys.exit(1)
            return self._args.max_requests
        return sum(stages) * self._args.num_rounds

    # pylint: disable=too-many-arguments
    def confirm_cost(
            self, stages, total_cap, *, runner,
            output_dir=None, stale_log_age=None,
    ) -> Optional[RequestResult]:
        """Display PRE-RUN SUMMARY and optionally run a dry-run probe.

        With --yes: shows the summary and returns immediately.
        Without --yes: fires one probe request with --tokens to
        measure actual token usage, collects warnings, and asks
        the user to confirm.

        Returns the probe result dict if a probe was run, else None.
        """
        total_planned = sum(stages) * self._args.num_rounds
        capped = min(total_planned, total_cap)

        self._print_summary_header(stages, total_planned, capped)

        if self._args.yes:
            warnings = self._collect_warnings(
                capped=capped,
                total_planned=total_planned,
                stale_log_age=stale_log_age,
            )
            self._print_warnings(warnings)
            logger.info("=" * SEPARATOR_WIDTH)
            return None

        probe_result, probe_data = (
            self._run_cost_probe(runner, output_dir)
        )

        remaining = max(capped - 1, 0)
        est_stage_duration = self._estimate_stage_duration(
            probe_data.get("elapsed", 0), remaining,
        )
        logger.info(
            "  Estimated stage duration: ~%ss "
            "(%.1fs x %s requests)",
            int(est_stage_duration),
            probe_data.get("elapsed", 0),
            remaining,
        )

        warnings = self._collect_warnings(
            capped=capped,
            total_planned=total_planned,
            stale_log_age=stale_log_age,
            est_stage_duration=est_stage_duration,
            probe_tokens=probe_data.get("tokens", 0),
            probe_cost=probe_data.get("cost", 0.0),
            probe_model=probe_data.get("model", "unknown"),
        )
        self._print_warnings(warnings)

        if self._args.level != LEVEL_ADV:
            logger.info(
                "\n  Tip: use --yes at adv level to skip "
                "this confirmation.\n"
                "       --yes does not auto-adjust timeouts.",
            )

        logger.info("=" * SEPARATOR_WIDTH)

        prompt = (
            "\nProceed with remaining "
            f"{capped - 1} requests? [y/n]: "
        )
        while True:
            try:
                answer = input(prompt).strip().lower()
            except (EOFError, KeyboardInterrupt):
                logger.info("\nAborted by user.")
                sys.exit(0)
            if answer in ("y", "yes"):
                break
            if answer in ("n", "no"):
                logger.info("Aborted by user.")
                sys.exit(0)
            logger.info("  Please answer 'y' or 'n'.")

        return probe_result

    def _print_summary_header(
            self, stages, total_planned, capped,
    ) -> None:
        """Print the PRE-RUN SUMMARY header block."""
        args = self._args
        logger.info("\n%s", "=" * SEPARATOR_WIDTH)
        logger.info("  PRE-RUN SUMMARY")
        logger.info("=" * SEPARATOR_WIDTH)
        logger.info("  Agent:    %s", args.agent)
        logger.info("  Level:    %s", args.level)
        if args.ramp:
            logger.info(
                "  Stages:   %s", stages,
            )
        logger.info(
            "  Requests: %s x %s round%s = %s total",
            args.num_requests,
            args.num_rounds,
            "s" if args.num_rounds > 1 else "",
            total_planned,
        )
        if capped < total_planned:
            logger.info(
                "  Capped:   %s (--max-requests)", capped,
            )
        logger.info(
            "  Workers:  %s (concurrent)", args.max_workers,
        )
        logger.info(
            "  Timeouts: --request-timeout %ss (%sm) / "
            "--idle-timeout %ss (%sm) / "
            "--stage-timeout %ss (%sm)",
            args.request_timeout, args.request_timeout // 60,
            args.idle_timeout, args.idle_timeout // 60,
            args.stage_timeout, args.stage_timeout // 60,
        )
        if args.total_timeout > 0:
            logger.info(
                "            --total-timeout %ss (%sm)",
                args.total_timeout, args.total_timeout // 60,
            )
        else:
            logger.info(
                "            --total-timeout disabled",
            )
        self._print_system_memory()
        self._print_system_cpu()
        self._print_system_threads()

    @staticmethod
    def _print_system_memory() -> None:
        """Print total and available system memory."""
        mem = psutil.virtual_memory()
        total_gb = mem.total / (1024 ** 3)
        avail_gb = mem.available / (1024 ** 3)
        logger.info(
            "  System RAM: %.1fG (%.1fG available,"
            " %.0f%% used)",
            total_gb, avail_gb, mem.percent,
        )

    @staticmethod
    def _print_system_cpu() -> None:
        """Print core count and current system CPU utilization."""
        ncores = psutil.cpu_count() or 1
        cpu_pct = psutil.cpu_percent(interval=0.1)
        logger.info(
            "  System CPU: %d cores (%.0f%% in use)",
            ncores, cpu_pct,
        )

    @staticmethod
    def _print_system_threads() -> None:
        """Print current thread count and OS thread/process limits."""
        total_threads = 0
        for proc in psutil.process_iter(["num_threads"]):
            try:
                total_threads += proc.info["num_threads"] or 0
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        try:
            soft, _ = resource.getrlimit(resource.RLIMIT_NPROC)
            user_limit = (
                "unlimited"
                if soft == resource.RLIM_INFINITY
                else f"{soft:,}"
            )
        except (ValueError, OSError, AttributeError):
            user_limit = "n/a"
        sys_max = "n/a"
        try:
            with open(
                "/proc/sys/kernel/threads-max",
                encoding="utf-8",
            ) as handle:
                sys_max = f"{int(handle.read().strip()):,}"
        except (OSError, ValueError):
            pass
        logger.info(
            "  System threads: %s in use / limit %s"
            " per-user (%s max)",
            f"{total_threads:,}", user_limit, sys_max,
        )

    @staticmethod
    def _estimate_stage_duration(
            probe_elapsed, remaining,
    ) -> float:
        """Estimate stage wall time from probe duration.

        LLM is the bottleneck, so concurrent requests do not
        scale linearly.  Estimate as probe_time x remaining
        requests (the probe already ran, so it is excluded).
        """
        return probe_elapsed * remaining

    def _collect_warnings(
            self, *, capped, total_planned,
            stale_log_age=None,
            est_stage_duration=None,
            probe_tokens=None, probe_cost=None,
            probe_model=None,
    ) -> List[str]:
        """Collect all pre-run warnings as a list of strings."""
        warnings: List[str] = []

        if probe_cost is not None and probe_tokens:
            est_total_cost = probe_cost * capped
            est_total_tokens = probe_tokens * capped
            if est_total_cost > 1.0:
                warnings.append(
                    f"Estimated cost exceeds $1:\n"
                    f"     Probe used ~{probe_tokens:,} "
                    f"tokens (${probe_cost:.2f}) "
                    f"x {capped} requests = "
                    f"~{est_total_tokens:,} tokens "
                    f"(~${est_total_cost:.2f})\n"
                    f"     Model: {probe_model}"
                )

        max_w = self._args.max_workers
        num_r = self._args.num_requests
        if not self._args.ramp and max_w < num_r:
            warnings.append(
                f"--max-workers ({max_w}) < "
                f"--num-requests ({num_r}): "
                f"requests run in batches"
            )

        if (est_stage_duration is not None
                and est_stage_duration
                > self._args.stage_timeout):
            stage_to = self._args.stage_timeout
            warnings.append(
                f"Estimated stage duration "
                f"~{int(est_stage_duration)}s "
                f"exceeds --stage-timeout ({stage_to}s).\n"
                f"     Requests may be killed "
                f"before completing."
            )

        if capped < total_planned:
            warnings.append(
                f"--max-requests ({capped}) "
                f"caps planned total ({total_planned})"
            )

        if stale_log_age is not None:
            warnings.append(
                f"Server log appears stale "
                f"(last modified {stale_log_age}m ago)"
            )

        mem_warning = self._check_memory_headroom(
            capped,
            http_client=getattr(
                self._args, "http_client", False,
            ),
        )
        if mem_warning:
            warnings.append(mem_warning)

        return warnings

    @staticmethod
    def _check_memory_headroom(
            num_requests, *, http_client=False,
    ) -> Optional[str]:
        """Warn if available memory looks insufficient.

        Uses a conservative per-request estimate based on
        typical server thread overhead.
        """
        mem = psutil.virtual_memory()
        avail_gb = mem.available / (1024 ** 3)
        per_request_mb = 2 if http_client else 50
        needed_gb = (num_requests * per_request_mb) / 1024
        if needed_gb > avail_gb * 0.8:
            return (
                f"Memory may be insufficient for"
                f" {num_requests} concurrent requests:\n"
                f"     Estimated need:"
                f" ~{needed_gb:.1f}G"
                f" ({num_requests} x ~{per_request_mb}MB"
                f" per request)\n"
                f"     Available: {avail_gb:.1f}G"
                f" / {mem.total / (1024 ** 3):.1f}G total\n"
                f"     Consider fewer concurrent workers"
                f" or a larger instance"
            )
        return None

    @staticmethod
    def _print_warnings(warnings) -> None:
        """Print numbered warnings or 'No warnings'."""
        if not warnings:
            logger.info("\n  No warnings.")
            return

        logger.warning(
            "\n  WARNINGS (%s found):", len(warnings),
        )
        for idx, warning in enumerate(warnings, 1):
            lines = warning.split("\n")
            logger.warning("  %s. %s", idx, lines[0])
            for line in lines[1:]:
                logger.warning("  %s", line)

    def _run_cost_probe(
            self, runner, output_dir,
    ) -> Tuple[RequestResult, dict]:
        """Fire one probe request and return results.

        Fires a single request (tokens are enabled by default)
        and logs the outcome.

        Returns (probe_result, probe_data_dict).
        """
        logger.info(
            "\n  Running 1 dry-run probe to measure actual "
            "cost...",
        )

        probe_result = runner.run_one(
            request_id=0, global_request_id=0,
            output_dir=output_dir,
        )

        probe_tokens = probe_result.get("total_tokens", 0)
        probe_cost = probe_result.get("cost_usd", 0.0)
        probe_model = probe_result.get("model", "unknown")
        probe_status = probe_result.get("status", "FAILED")
        probe_elapsed = probe_result.get("elapsed", 0)

        logger.info(
            "\n  Probe request completed in %.1fs (%s)",
            probe_elapsed, probe_status,
        )

        if probe_tokens > 0:
            logger.info(
                "  Probe tokens: %s (model: %s, cost: $%.4f)",
                f"{probe_tokens:,}", probe_model, probe_cost,
            )
        else:
            logger.info(
                "  No token data from probe (agent may not "
                "track tokens).",
            )

        probe_data = {
            "tokens": probe_tokens,
            "cost": probe_cost,
            "model": probe_model,
            "elapsed": probe_elapsed,
        }
        return probe_result, probe_data
