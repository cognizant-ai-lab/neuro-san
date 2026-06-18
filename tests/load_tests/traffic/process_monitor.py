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

"""Subprocess execution with idle-timeout and hard-timeout detection."""

import logging
import os
import subprocess
import sys
import time
from typing import List
from typing import Optional
from typing import Tuple

from tests.load_tests.config import POLL_INTERVAL_SECONDS
from tests.load_tests.config import PROCESS_WAIT_TIMEOUT
from tests.load_tests.config import READ_BUFFER_SIZE
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_KILLED
from tests.load_tests.config import STATUS_TIMEOUT

logger = logging.getLogger(__name__)


class ProcessMonitor:
    """Runs subprocesses with idle-timeout and hard-timeout detection."""

    @staticmethod
    def execute_with_idle_detection(
            cmd, timeout, idle_timeout,
    ) -> Tuple[str, str, str, int, float]:
        """Run a subprocess with idle-timeout and hard-timeout detection.

        Returns (status, stdout, stderr, returncode, ttft).
        ttft is time-to-first-token in seconds (0.0 if no stdout).
        """
        stdout_chunks: List[bytes] = []
        stderr_chunks: List[bytes] = []
        status = STATUS_FAILED
        ttft_ref: List[float] = []

        try:
            # pylint: disable=consider-using-with
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            return (STATUS_FAILED, "", str(exc), -1, 0.0)

        try:
            monitor_status = ProcessMonitor._monitor_process(
                proc, stdout_chunks, stderr_chunks,
                timeout=timeout, idle_timeout=idle_timeout,
                ttft_ref=ttft_ref,
            )
            if monitor_status is not None:
                status = monitor_status
        except (OSError, subprocess.SubprocessError):
            proc.kill()
            proc.wait()
            status = STATUS_FAILED

        if not proc.stdout.closed:
            remaining_out = proc.stdout.read()
            if remaining_out:
                stdout_chunks.append(remaining_out)
        if not proc.stderr.closed:
            remaining_err = proc.stderr.read()
            if remaining_err:
                stderr_chunks.append(remaining_err)
        try:
            proc.wait(timeout=PROCESS_WAIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            if status == STATUS_FAILED:
                status = STATUS_KILLED

        ttft = ttft_ref[0] if ttft_ref else 0.0
        return (
            status,
            b"".join(stdout_chunks).decode("utf-8", errors="replace"),
            b"".join(stderr_chunks).decode("utf-8", errors="replace"),
            proc.returncode,
            ttft,
        )

    @staticmethod
    # pylint: disable=too-many-arguments
    def _monitor_process(proc, stdout_chunks,
                         stderr_chunks, *,
                         timeout, idle_timeout,
                         ttft_ref) -> Optional[str]:
        """Monitor a running process for output, idle timeout, and hard timeout.

        Returns STATUS_TIMEOUT or STATUS_KILLED for abnormal exits,
        or None when the process exits normally (caller determines
        final status from the return code).
        """
        if sys.platform == "win32":
            return ProcessMonitor._monitor_process_win(
                proc, stdout_chunks, stderr_chunks,
                timeout=timeout,
            )
        return ProcessMonitor._monitor_process_unix(
            proc, stdout_chunks, stderr_chunks,
            timeout=timeout, idle_timeout=idle_timeout,
            ttft_ref=ttft_ref,
        )

    @staticmethod
    # pylint: disable=too-many-arguments
    def _monitor_process_unix(proc, stdout_chunks,
                              stderr_chunks, *,
                              timeout, idle_timeout,
                              ttft_ref) -> Optional[str]:
        """Unix implementation using select() for idle-timeout detection."""
        import select  # pylint: disable=import-outside-toplevel
        start = time.time()
        last_activity = time.time()
        while proc.poll() is None:
            elapsed = time.time() - start
            idle_elapsed = time.time() - last_activity

            if elapsed >= timeout:
                proc.kill()
                proc.wait()
                return STATUS_TIMEOUT

            if idle_elapsed >= idle_timeout:
                proc.kill()
                proc.wait()
                return STATUS_KILLED

            readable, _, _ = select.select(
                [proc.stdout, proc.stderr], [], [],
                POLL_INTERVAL_SECONDS,
            )
            for stream in readable:
                data = os.read(stream.fileno(), READ_BUFFER_SIZE)
                if data:
                    last_activity = time.time()
                    if stream == proc.stdout:
                        if not ttft_ref:
                            ttft_ref.append(
                                time.time() - start,
                            )
                        stdout_chunks.append(data)
                    else:
                        stderr_chunks.append(data)
        return None

    @staticmethod
    def _monitor_process_win(proc, stdout_chunks,
                             stderr_chunks, *,
                             timeout) -> Optional[str]:
        """Windows fallback using communicate() (hard-timeout only)."""
        try:
            out, err = proc.communicate(timeout=timeout)
            if out:
                stdout_chunks.append(out)
            if err:
                stderr_chunks.append(err)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return STATUS_TIMEOUT
        return None
