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

"""Recommendations engine — actionable suggestions based on load test results."""

import logging
import os
from typing import List
from typing import Optional

from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.config import STATUS_KILLED

logger = logging.getLogger(__name__)


class RecommendationEngine:
    """Generates actionable suggestions based on load test results."""

    @staticmethod
    def log_recommendations(
            stage_summaries, args=None, output_dir=None,
    ):
        """Log actionable recommendations and write to file."""
        recommendations = RecommendationEngine._detect_issues(
            stage_summaries,
        )
        observations = RecommendationEngine._summarize_observations(
            stage_summaries,
        )
        suggestion = RecommendationEngine._suggest_next_step(
            stage_summaries, args,
        )

        lines = []
        lines.append("")
        lines.append("=" * 60)
        lines.append("  RECOMMENDATIONS")
        lines.append("=" * 60)

        if recommendations:
            for idx, rec in enumerate(recommendations, 1):
                lines.append(f"  {idx}. {rec}")
                lines.append("")
        else:
            total_reqs = sum(
                s.get("concurrent", 0) for s in stage_summaries
            )
            max_concurrent = max(
                (s.get("concurrent", 0) for s in stage_summaries),
                default=0,
            )
            lines.append(
                f"  No issues detected at current load "
                f"({total_reqs} requests, "
                f"max {max_concurrent} concurrent).",
            )
            lines.append("")

        if observations:
            lines.append("  Observations:")
            for obs in observations:
                lines.append(f"  {obs}")
            lines.append("")

        if suggestion:
            lines.append(f"  {suggestion}")
            lines.append("")

        for line in lines:
            logger.info(line)

        if output_dir:
            RecommendationEngine._write_recommendations_file(
                output_dir, lines,
            )

    # pylint: disable=too-many-locals
    @staticmethod
    def _detect_issues(stage_summaries) -> List[str]:
        """Detect issues from pool reuse and resource data."""
        stages_with_data = [
            s for s in stage_summaries
            if s.get("before_threads") is not None
            and s.get("after_threads") is not None
            and s.get("total_started") is not None
            and s.get("total_started") > 0
        ]

        recommendations = []

        if len(stages_with_data) >= 2:
            base_threads = stages_with_data[0].get("before_threads")

            stage2 = stages_with_data[1]
            server_calls_2 = stage2.get("total_started")
            new_threads_2 = max(
                stage2.get("after_threads")
                - stage2.get("before_threads"), 0,
            )
            reused_2 = max(server_calls_2 - new_threads_2, 0)
            reuse_pct_2 = (
                (reused_2 / server_calls_2 * 100.0)
                if server_calls_2 > 0 else 0.0
            )
            pool_avail_2 = max(
                stage2.get("before_threads") - base_threads, 0,
            )
            if reuse_pct_2 < 50.0 and pool_avail_2 > 0:
                recommendations.append(
                    f"POOL LOCK CONTENTION: Batch 2 reuse was "
                    f"{reuse_pct_2:.1f}% despite {pool_avail_2} "
                    f"executors available.\n"
                    f"     return_executor() calls "
                    f"cancel_current_tasks() while holding the "
                    f"pool lock\n"
                    f"     (up to 5s per executor), starving "
                    f"get_executor(). Fix: move cancellation\n"
                    f"     outside the lock."
                )

            first_stage = stages_with_data[0]
            primary_1 = (
                first_stage.get("primary_started")
                or first_stage.get("concurrent")
            )
            calls_1 = first_stage.get("total_started")
            if primary_1 > 0:
                multiplier = calls_1 / primary_1
                if multiplier > 2.0:
                    recommendations.append(
                        f"HIGH EXECUTOR MULTIPLIER: "
                        f"{multiplier:.1f} server calls per request.\n"
                        f"     Each sub-agent call makes an HTTP "
                        f"loopback that allocates a separate\n"
                        f"     executor+thread "
                        f"(use_direct=False in "
                        f"ExternalAgentSessionFactory)."
                    )

            last_stage = stages_with_data[-1]
            final_threads = last_stage.get("after_threads")
            total_new = final_threads - base_threads
            if total_new > 500:
                recommendations.append(
                    f"UNBOUNDED POOL GROWTH: {final_threads} threads "
                    f"after test with no cap.\n"
                    f"     {total_new} executor threads created and "
                    f"never shut down (reuse_mode=True).\n"
                    f"     Consider adding max_pool_size with "
                    f"executor shutdown for excess."
                )

        all_results = []
        for s in stage_summaries:
            all_results.extend(s.get("results", []))
        total = len(all_results)
        failed = sum(
            1 for r in all_results
            if r.get("status") in (
                STATUS_FAILED, STATUS_TIMEOUT, STATUS_KILLED,
            )
        )
        if total > 0 and failed > 0:
            fail_pct = failed / total * 100
            recommendations.append(
                f"FAILURES DETECTED: {failed}/{total} requests "
                f"failed ({fail_pct:.0f}%).\n"
                f"     Review per-request CSV for failure details "
                f"and server log for errors."
            )

        return recommendations

    @staticmethod
    def _summarize_observations(stage_summaries) -> List[str]:
        """Build a list of observation bullet points."""
        observations = []

        all_results = []
        for s in stage_summaries:
            all_results.extend(s.get("results", []))
        total = len(all_results)
        if total == 0:
            return observations

        created = sum(
            1 for r in all_results
            if r.get("status") == STATUS_CREATED
        )
        failed = sum(
            1 for r in all_results
            if r.get("status") == STATUS_FAILED
        )
        timed_out = sum(
            1 for r in all_results
            if r.get("status") == STATUS_TIMEOUT
        )
        total_retries = sum(
            s.get("total_retries", 0) for s in stage_summaries
        )
        observations.append(
            f"\u2022 {created} completed, {failed} failed, "
            f"{timed_out} timed out, {total_retries} retries",
        )

        stage_latencies = []
        for s in stage_summaries:
            results = s.get("results", [])
            if results:
                avg = (
                    sum(r.get("elapsed", 0) for r in results)
                    / len(results)
                )
                stage_latencies.append(f"{avg:.1f}s")
        if stage_latencies:
            overall_avg = (
                sum(r.get("elapsed", 0) for r in all_results) / total
            )
            latency_str = " \u2192 ".join(stage_latencies)
            observations.append(
                f"\u2022 Avg latency: {overall_avg:.1f}s "
                f"(per stage: {latency_str})",
            )

        stages_with_resources = [
            s for s in stage_summaries
            if s.get("before_threads") is not None
        ]
        if stages_with_resources:
            first = stages_with_resources[0]
            last = stages_with_resources[-1]
            before_threads = first.get("before_threads", 0)
            after_threads = last.get("after_threads", 0)
            thread_delta = after_threads - before_threads
            observations.append(
                f"\u2022 Thread growth: +{thread_delta} "
                f"({before_threads} \u2192 {after_threads})",
            )

        reuse_rates = []
        if len(stages_with_resources) >= 2:
            for s in stages_with_resources:
                calls = s.get("total_started", 0)
                new_t = max(
                    s.get("after_threads", 0)
                    - s.get("before_threads", 0), 0,
                )
                reused = max(calls - new_t, 0)
                pct = (reused / calls * 100) if calls > 0 else 0
                reuse_rates.append(f"{pct:.0f}%")
            if reuse_rates:
                reuse_str = " \u2192 ".join(reuse_rates)
                observations.append(
                    f"\u2022 Pool reuse: {reuse_str}",
                )

        token_totals = [
            r.get("total_tokens", 0) for r in all_results
            if r.get("total_tokens")
        ]
        if token_totals:
            total_tokens = sum(token_totals)
            avg_tokens = total_tokens // len(token_totals)
            models = set(
                r.get("model") for r in all_results if r.get("model")
            )
            model_str = (
                ", ".join(sorted(models)) if models else "unknown"
            )
            observations.append(
                f"\u2022 Tokens: {total_tokens:,} total "
                f"(avg {avg_tokens:,}/request), model: {model_str}",
            )

        return observations

    @staticmethod
    def _suggest_next_step(
        stage_summaries, args=None,
    ) -> Optional[str]:
        """Generate a suggestion for the next test run."""
        if not stage_summaries:
            return None

        agent = (
            getattr(args, "agent", "hello_world")
            if args else "hello_world"
        )
        is_ramp = (
            getattr(args, "ramp", False) if args else False
        )
        stages_used = []
        for s in stage_summaries:
            concurrent = s.get("concurrent", 0)
            if concurrent not in stages_used:
                stages_used.append(concurrent)

        extra_flags = []
        if args:
            if getattr(args, "server_log", None):
                extra_flags.append(
                    f"--server-log {args.server_log}",
                )
            if getattr(args, "project_root", None):
                extra_flags.append(
                    f"--project-root {args.project_root}",
                )
        extra_str = (
            " \\\n        "
            + " \\\n        ".join(extra_flags)
            if extra_flags else ""
        )

        if is_ramp:
            next_stages = [s * 2 for s in stages_used]
            stages_str = ",".join(str(s) for s in next_stages)
            return (
                f"Next step \u2014 increase concurrency to find the "
                f"server's capacity limit:\n"
                f"    python -m tests.load_tests.load_test "
                f"--agent {agent} \\\n"
                f"        --level adv --ramp "
                f"--stages {stages_str} --yes{extra_str}"
            )

        max_workers = max(stages_used) if stages_used else 2
        ramp_stages = [
            max_workers, max_workers * 2, max_workers * 4,
        ]
        stages_str = ",".join(str(s) for s in ramp_stages)
        return (
            f"Next step \u2014 try ramp-up mode to find the "
            f"server's capacity limit:\n"
            f"    python -m tests.load_tests.load_test "
            f"--agent {agent} \\\n"
            f"        --level adv --ramp "
            f"--stages {stages_str} --yes{extra_str}"
        )

    @staticmethod
    def _write_recommendations_file(output_dir, lines):
        """Write recommendations to a text file in the output directory."""
        filepath = os.path.join(output_dir, "recommendations.txt")
        with open(filepath, "w", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line.rstrip("\n") + "\n")
        logger.info("Recommendations: %s", filepath)
