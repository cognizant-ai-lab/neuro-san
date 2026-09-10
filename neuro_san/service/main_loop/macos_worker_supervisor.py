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
    Supervises fresh worker processes for multi-instance service startup on macOS.

    Tornado normally implements multiple HTTP server instances by calling fork().
    Forking on macOS is unsafe after Objective-C-backed system libraries have
    initialized, and can abort a worker when it handles its first request. Setting
    OBJC_DISABLE_INITIALIZE_FORK_SAFETY avoids that abort by disabling the runtime
    safeguard, but leaves the unsafe process model in place.

    Instead, this supervisor starts each worker in a fresh Python interpreter.
    Workers identify themselves through WORKER_ENV, run one Tornado instance, and
    bind the shared HTTP port with SO_REUSEPORT. Non-macOS platforms retain the
    existing Tornado worker process behavior.
    """

    WORKER_ENV: str = "NEURO_SAN_MACOS_WORKER"

    @staticmethod
    def is_worker() -> bool:
        """
        Return whether this process was started as a supervised macOS worker.

        This check also prevents a worker from recursively becoming another
        supervisor when it executes the service entry point.
        """
        return sys.platform == "darwin" and os.environ.get(MacOsWorkerSupervisor.WORKER_ENV) == "1"

    @staticmethod
    def run() -> int:
        """
        Start fresh macOS worker processes instead of forking this process.

        :return: The supervisor exit code, or -1 when no supervisor is needed.
        """
        # Only replace Tornado's fork-based startup on macOS. A worker must
        # continue into ServerMainLoop instead of recursively supervising.
        if sys.platform != "darwin" or MacOsWorkerSupervisor.is_worker():
            return -1

        # Parse only the instance argument here. ServerMainLoop remains
        # responsible for validating and parsing every other service option.
        arg_parser = ArgumentParser(add_help=False)
        arg_parser.add_argument(
            "--http_server_instances",
            type=int,
            default=int(os.environ.get("AGENT_HTTP_SERVER_INSTANCES", DEFAULT_HTTP_SERVER_INSTANCES)),
        )
        args, _ = arg_parser.parse_known_args()
        # A single instance never forks, so it is already safe on macOS.
        if args.http_server_instances == 1:
            return -1

        # Match Tornado's documented meaning of 0: one worker per CPU core.
        worker_count = args.http_server_instances
        if worker_count == 0:
            worker_count = os.cpu_count() or 1
        if worker_count < 0:
            raise ValueError("http_server_instances must be greater than or equal to 0")

        # Mark each fresh interpreter as a worker. ServerMainLoop uses this
        # marker to select one Tornado instance with shared-port binding.
        worker_env = os.environ.copy()
        worker_env[MacOsWorkerSupervisor.WORKER_ENV] = "1"
        worker_command = [sys.executable, *sys.orig_argv[1:]]

        # ExitStack closes every Popen resource even when startup, signal
        # handling, or worker monitoring raises an exception.
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

            # Keep supervising until any worker exits. A worker failure should
            # stop its peers and become the supervisor's process exit status.
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
