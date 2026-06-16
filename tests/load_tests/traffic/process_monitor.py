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
import select
import subprocess
import time
from typing import List
from typing import Tuple

from tests.load_tests.config import PROCESS_WAIT_TIMEOUT
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_KILLED
from tests.load_tests.config import STATUS_TIMEOUT

logger = logging.getLogger(__name__)


class ProcessMonitor:
    """Runs subprocesses with idle-timeout and hard-timeout detection."""

    @staticmethod
    def execute_with_idle_detection(
            cmd, timeout, idle_timeout,
    ) -> Tuple[str, str, str, int]:
        """Run a subprocess with idle-timeout and hard-timeout detection.

        Returns (status, stdout, stderr, returncode).
        """
        stdout_chunks: List[bytes] = []
        stderr_chunks: List[bytes] = []
        status = STATUS_FAILED
        last_activity = time.time()

        # pylint: disable=consider-using-with
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            status = ProcessMonitor._monitor_process(
                proc, stdout_chunks, stderr_chunks,
                last_activity,
                timeout=timeout, idle_timeout=idle_timeout,
            )
        except (OSError, subprocess.SubprocessError):
            proc.kill()
            proc.wait()
            status = STATUS_FAILED

        remaining_out = proc.stdout.read()
        remaining_err = proc.stderr.read()
        if remaining_out:
            stdout_chunks.append(remaining_out)
        if remaining_err:
            stderr_chunks.append(remaining_err)
        try:
            proc.wait(timeout=PROCESS_WAIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            if status != STATUS_FAILED:
                status = STATUS_KILLED

        return (
            status,
            b"".join(stdout_chunks).decode("utf-8", errors="replace"),
            b"".join(stderr_chunks).decode("utf-8", errors="replace"),
            proc.returncode,
        )

    # pylint: disable=too-many-arguments
    @staticmethod
    def _monitor_process(proc, stdout_chunks,
                         stderr_chunks, last_activity, *,
                         timeout, idle_timeout) -> str:
        """Monitor a running process for output, idle timeout, and hard timeout."""
        start = time.time()
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
                [proc.stdout, proc.stderr], [], [], 5.0,
            )
            for stream in readable:
                data = os.read(stream.fileno(), 4096)
                if data:
                    last_activity = time.time()
                    if stream == proc.stdout:
                        stdout_chunks.append(data)
                    else:
                        stderr_chunks.append(data)
        return STATUS_FAILED
