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
Supervisor for managing fresh worker processes in multi-instance HTTP server mode.
"""
from contextlib import ExitStack
from typing import Any
from typing import List
from typing import Optional

import os
import signal
import subprocess
import sys
import time

from argparse import ArgumentParser

from neuro_san.service.http.config.http_server_config import DEFAULT_HTTP_SERVER_INSTANCES


class WorkerSupervisor:
    """
    Supervises fresh worker processes for multi-instance service startup across platforms.

    Rather than relying on fork() (which is unsafe on macOS due to Objective-C runtime
    restrictions, unavailable on Windows, and prone to thread/lock inheritance bugs on Linux),
    this supervisor starts each worker in a fresh Python interpreter.

    Each worker:
      - Is identified by the WORKER_ENV environment variable
      - Is assigned a unique worker ID (0-based) via WORKER_ID_ENV
      - Receives the total worker count via NUM_WORKERS_ENV
      - Runs one Tornado instance with SO_REUSEPORT enabled
      - Worker 0 executes designated singleton background tasks (e.g. S3 expiration checks,
        single-instance watchers), while workers > 0 skip them.

    The supervisor forwards termination signals (SIGINT, SIGTERM) to all worker processes
    and propagates worker exit statuses upon process completion.
    """

    WORKER_ENV: str = "NEURO_SAN_WORKER"
    WORKER_ID_ENV: str = "NEURO_SAN_WORKER_ID"
    NUM_WORKERS_ENV: str = "NEURO_SAN_NUM_WORKERS"

    @staticmethod
    def is_worker() -> bool:
        """
        Return whether this process was started as a supervised worker.

        This check also prevents a worker from recursively becoming another
        supervisor when it executes the service entry point.
        """
        return os.environ.get(WorkerSupervisor.WORKER_ENV) == "1"

    @staticmethod
    def get_worker_id() -> int:
        """
        Return the 0-based worker ID of this process, or 0 if not running as a supervised worker.
        """
        try:
            return int(os.environ.get(WorkerSupervisor.WORKER_ID_ENV, "0"))
        except ValueError:
            return 0

    @staticmethod
    def get_num_workers() -> int:
        """
        Return the total number of workers, or 1 if not running as a supervised worker.
        """
        try:
            return int(os.environ.get(WorkerSupervisor.NUM_WORKERS_ENV, "1"))
        except ValueError:
            return 1

    active_workers: List[subprocess.Popen] = []

    @classmethod
    def stop_workers(cls, _signal_number: Optional[int] = None, _frame: Optional[Any] = None):
        """
        Terminate every worker which is still running.

        :param _signal_number: Signal number passed by signal handler (optional).
        :param _frame: Stack frame passed by signal handler (optional).
        """
        for worker in cls.active_workers:
            if worker.poll() is None:
                worker.terminate()

    @classmethod
    def run(cls) -> int:
        """
        Start fresh worker processes instead of forking this process.

        :return: The supervisor exit code, or -1 when no supervisor is needed.
        """
        # A worker must continue into ServerMainLoop instead of recursively supervising.
        if cls.is_worker():
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

        # A single instance never forks, so it does not need a supervisor.
        if args.http_server_instances == 1:
            return -1

        # Match documented meaning of 0: one worker per CPU core.
        worker_count = args.http_server_instances
        if worker_count < 0:
            raise ValueError("http_server_instances must be greater than or equal to 0")

        if sys.platform.startswith("win"):
            raise NotImplementedError(
                "Multi-instance HTTP server is not supported on Windows "
                "because Windows does not support SO_REUSEPORT."
            )

        if worker_count == 0:
            worker_count = os.cpu_count() or 1

        orig_argv = getattr(sys, "orig_argv", None)
        if orig_argv is not None and len(orig_argv) > 1:
            worker_command = [sys.executable, *orig_argv[1:]]
        else:
            worker_command = [sys.executable, *sys.argv]

        # ExitStack closes every Popen resource even when startup, signal
        # handling, or worker monitoring raises an exception.
        try:
            with ExitStack() as stack:
                cls.active_workers = []
                for i in range(worker_count):
                    worker_env = os.environ.copy()
                    worker_env[cls.WORKER_ENV] = "1"
                    worker_env[cls.WORKER_ID_ENV] = str(i)
                    worker_env[cls.NUM_WORKERS_ENV] = str(worker_count)
                    cls.active_workers.append(
                        stack.enter_context(subprocess.Popen(worker_command, env=worker_env))
                    )

                signal.signal(signal.SIGINT, cls.stop_workers)
                signal.signal(signal.SIGTERM, cls.stop_workers)

                # Keep supervising until any worker exits. A worker failure should
                # stop its peers and become the supervisor's process exit status.
                while not any(worker.poll() is not None for worker in cls.active_workers):
                    time.sleep(0.1)

                exit_code = next(
                    (worker.returncode for worker in cls.active_workers if worker.returncode not in (None, 0)),
                    0,
                )
                cls.stop_workers()
                for worker in cls.active_workers:
                    worker.wait()
                return exit_code
        finally:
            cls.active_workers = []
