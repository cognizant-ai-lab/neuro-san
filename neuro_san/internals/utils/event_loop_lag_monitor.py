
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
"""
See class comment for details
"""

import asyncio
import statistics
import time
from typing import List


class EventLoopLagMonitor:
    """
    Periodically samples asyncio event-loop responsiveness by scheduling a
    sleep at fixed intervals and measuring how much actual wake-up time
    slipped from the scheduled time. A perfectly responsive loop reports
    lag near zero; a loop blocked by a sync call shows lag equal to the
    duration of that block.

    Run with create_task(monitor.run()); cancel the task to stop.
    """

    def __init__(self, sample_interval_seconds: float = 0.1,
                 report_every_n_samples: int = 50,
                 break_between_reports_seconds: float = 0.0,
                 logger=None):
        """
        :param sample_interval_seconds: Time between samples. Smaller = finer
                                  resolution but more CPU. 0.05-0.1s is typical.
        :param report_every_n_samples: How many samples to aggregate before
                                  emitting a report.
        :param break_between_reports_seconds: Optional sleep after each report to
                                  reduce logging clutter.
        :param logger: Optional logger; falls back to print().
        """
        self.interval: float = sample_interval_seconds
        self.batch_size: int = report_every_n_samples
        self.break_between_reports: float = break_between_reports_seconds
        self.logger = logger
        self.task = None
        self._samples: List[float] = []
        self.max_p50_ms: float = 0.0
        self.max_p95_ms: float = 0.0
        self.max_mean_ms: float = 0.0
        self.max_max_ms: float = 0.0

    async def run(self) -> None:
        """
        Sampling loop. Cancel the surrounding task to stop.
        """
        expected = time.monotonic() + self.interval
        while True:
            await asyncio.sleep(self.interval)
            now = time.monotonic()
            lag = max(0.0, now - expected)
            self._samples.append(lag)

            if len(self._samples) >= self.batch_size:
                self._report()
                # Clear the samples after reporting.
                self._samples.clear()
                if self.break_between_reports > 0:
                    await asyncio.sleep(self.break_between_reports)

            now = time.monotonic()
            expected = now + self.interval  # resync so one big spike doesn't bias the rest

    def start(self) -> None:
        """
        Start the monitoring loop in a background task.
        """
        self.task = asyncio.create_task(self.run())

    def stop(self) -> None:
        if self.task:
            self.task.cancel()
            self.task = None

    def _report(self) -> None:
        """
        Compute and emit a report of the collected lag samples,
        including percentiles and mean.
        """
        samples = self._samples
        samples_ms = [s * 1000 for s in samples]
        samples_ms_sorted = sorted(samples_ms)
        n = len(samples_ms_sorted)
        p50 = samples_ms_sorted[n // 2]
        p95 = samples_ms_sorted[int(n * 0.95)]
        p99 = samples_ms_sorted[min(int(n * 0.99), n - 1)]
        self.max_p50_ms = max(self.max_p50_ms, p50)
        self.max_p95_ms = max(self.max_p95_ms, p95)
        mean_ms = statistics.fmean(samples_ms)
        max_samples_ms = max(samples_ms)
        self.max_mean_ms = max(self.max_mean_ms, mean_ms)
        self.max_max_ms = max(self.max_max_ms, max_samples_ms)
        msg = (f"Event loop lag (n={n}, interval={self.interval * 1000:.0f}ms): "
               f"p50={p50:.2f}ms p95={p95:.2f}ms p99={p99:.2f}ms "
               f"max={max_samples_ms:.2f}ms mean={mean_ms:.2f}ms "
               f"max_p50={self.max_p50_ms:.2f}ms max_p95={self.max_p95_ms:.2f}ms "
               f"max_max={self.max_max_ms:.2f}ms max_mean={self.max_mean_ms:.2f}ms")
        if self.logger:
            self.logger.info({}, msg)
        else:
            # Fall back to print if no logger provided.
            print(msg)
