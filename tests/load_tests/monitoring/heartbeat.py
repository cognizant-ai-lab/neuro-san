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

"""Progress heartbeat — periodic logging while requests are in-flight.

Interim implementation. May be replaced by neuro-san built-in
monitoring and telemetry when those features become available.
"""

import logging
import time

import psutil

logger = logging.getLogger(__name__)


class Heartbeat:
    """Logs periodic progress while requests are in-flight."""

    # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    @staticmethod
    def progress_heartbeat(futures, total, start_time, stop_event,
                           server_proc, peak_threads_result):
        """Log periodic progress while requests are in-flight."""
        interval = 30
        last_done = 0
        last_change = start_time
        peak_threads = 0
        while not stop_event.wait(timeout=interval):
            done = sum(1 for f in futures if f.done())
            elapsed = int(time.time() - start_time)
            ts = time.strftime("%H:%M:%S", time.localtime())
            pct = done * 100 // total if total > 0 else 0
            suffix = ""
            if done == last_done and done < total:
                stall = int(time.time() - last_change)
                suffix = f"  !! no new completions in {stall}s"
            if done > last_done:
                last_change = time.time()
                last_done = done
            thread_info = ""
            if server_proc is not None:
                try:
                    threads = server_proc.num_threads()
                    if threads > peak_threads:
                        peak_threads = threads
                        peak_threads_result.update({"peak": threads})
                        thread_info = f"  threads: {threads} (peak)"
                    else:
                        thread_info = f"  threads: {threads}"
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            logger.info(
                "  [progress] %s of %s completed"
                " (%s%%) -- %ss elapsed [%s]%s%s",
                done, total, pct, elapsed, ts,
                suffix, thread_info,
            )
