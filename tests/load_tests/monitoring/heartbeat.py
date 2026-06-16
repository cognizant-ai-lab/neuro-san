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
from typing import Optional

import psutil

from tests.load_tests.config import HEARTBEAT_INTERVAL_SECONDS
from tests.load_tests.config import SharedRef

logger = logging.getLogger(__name__)


class Heartbeat:
    """Logs periodic progress while requests are in-flight.

    Holds the server process handle so the heartbeat thread can
    read thread counts without the caller passing it each time.
    """

    def __init__(
            self, server_proc: Optional[psutil.Process],
            client_proc: Optional[psutil.Process] = None,
    ) -> None:
        self._server_proc = server_proc
        self._client_proc = client_proc

    def _sample_client_rss(self, peak_rss, peak_ref) -> float:
        """Sample client RSS and update peak if higher.

        Returns the current peak value.
        """
        if self._client_proc is None:
            return peak_rss
        try:
            rss = (
                self._client_proc.memory_info().rss / (1024 * 1024)
            )
            if rss > peak_rss:
                peak_rss = rss
                peak_ref.value = rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return peak_rss

    # pylint: disable=too-many-locals,too-many-arguments
    def progress_heartbeat(self, futures, total, start_time,
                           stop_event, *,
                           peak_threads_ref: SharedRef,
                           peak_client_rss_ref: SharedRef,
                           ) -> None:
        """Log periodic progress while requests are in-flight."""
        last_done = 0
        last_change = start_time
        peak_threads = 0
        peak_rss = self._sample_client_rss(0.0, peak_client_rss_ref)
        while not stop_event.wait(timeout=HEARTBEAT_INTERVAL_SECONDS):
            peak_rss = self._sample_client_rss(
                peak_rss, peak_client_rss_ref,
            )
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
            if self._server_proc is not None:
                try:
                    threads = self._server_proc.num_threads()
                    if threads > peak_threads:
                        peak_threads = threads
                        peak_threads_ref.value = threads
                        thread_info = f"  threads: {threads} (peak)"
                    else:
                        thread_info = f"  threads: {threads}"
                except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                    logger.debug("Heartbeat thread count unavailable: %s", exc)
            logger.info(
                "  [progress] %s of %s completed"
                " (%s%%) -- %ss elapsed [%s]%s%s",
                done, total, pct, elapsed, ts,
                suffix, thread_info,
            )
