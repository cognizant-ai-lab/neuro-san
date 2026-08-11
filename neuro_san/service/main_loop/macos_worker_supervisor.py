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
Supervises fresh worker processes for multi-instance service startup on macOS.
"""

from contextlib import ExitStack
from typing import List

import os
import signal
import subprocess
import sys
import time

from argparse import ArgumentParser

from neuro_san.service.http.config.http_server_config import DEFAULT_HTTP_SERVER_INSTANCES


class MacOsWorkerSupervisor:
    """
    Starts fresh Python interpreters instead of using unsafe fork() on macOS.
    """

    WORKER_ENV: str = "NEURO_SAN_MACOS_WORKER"

    @staticmethod
    def is_worker() -> bool:
        """Return whether this process was started as a supervised macOS worker."""
        return sys.platform == "darwin" and os.environ.get(MacOsWorkerSupervisor.WORKER_ENV) == "1"

    @staticmethod
    def run() -> int:
        """
        Start fresh macOS worker processes instead of forking this process.

        :return: The supervisor exit code, or -1 when no supervisor is needed.
        """
        if sys.platform != "darwin" or MacOsWorkerSupervisor.is_worker():
            return -1

        arg_parser = ArgumentParser(add_help=False)
        arg_parser.add_argument(
            "--http_server_instances",
            type=int,
            default=int(os.environ.get("AGENT_HTTP_SERVER_INSTANCES", DEFAULT_HTTP_SERVER_INSTANCES)),
        )
        args, _ = arg_parser.parse_known_args()
        if args.http_server_instances == 1:
            return -1

        worker_count = args.http_server_instances
        if worker_count == 0:
            worker_count = os.cpu_count() or 1
        if worker_count < 0:
            raise ValueError("http_server_instances must be greater than or equal to 0")

        worker_env = os.environ.copy()
        worker_env[MacOsWorkerSupervisor.WORKER_ENV] = "1"
        worker_command = [sys.executable, *sys.orig_argv[1:]]

        with ExitStack() as stack:
            workers: List[subprocess.Popen] = [
                stack.enter_context(subprocess.Popen(worker_command, env=worker_env))
                for _ in range(worker_count)
            ]

            def stop_workers(_signal_number, _frame):
                """Terminate every worker which is still running."""
                for worker in workers:
                    if worker.poll() is None:
                        worker.terminate()

            signal.signal(signal.SIGINT, stop_workers)
            signal.signal(signal.SIGTERM, stop_workers)

            while not any(worker.poll() is not None for worker in workers):
                time.sleep(0.1)

            exit_code = next(
                (worker.returncode for worker in workers if worker.returncode not in (None, 0)),
                0,
            )
            stop_workers(None, None)
            for worker in workers:
                worker.wait()
            return exit_code
