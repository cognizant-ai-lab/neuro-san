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
import select
import subprocess
import time
from typing import List
from typing import Tuple

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
        stdout_chunks: List[str] = []
        stderr_chunks: List[str] = []
        status = STATUS_FAILED
        last_activity = time.time()

        # pylint: disable=consider-using-with
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            status = ProcessMonitor._monitor_process(
                proc, stdout_chunks, stderr_chunks,
                last_activity, timeout, idle_timeout,
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
        proc.wait(timeout=10)

        return (
            status,
            "".join(stdout_chunks),
            "".join(stderr_chunks),
            proc.returncode,
        )

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    @staticmethod
    def _monitor_process(proc, stdout_chunks, stderr_chunks,
                         last_activity, timeout, idle_timeout):
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
                chunk = (
                    stream.read1(4096)
                    if hasattr(stream, "read1") else ""
                )
                if not chunk:
                    chunk = stream.readline()
                if chunk:
                    last_activity = time.time()
                    if stream == proc.stdout:
                        stdout_chunks.append(chunk)
                    else:
                        stderr_chunks.append(chunk)
        return STATUS_FAILED
