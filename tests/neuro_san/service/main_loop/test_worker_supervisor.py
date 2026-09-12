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
Unit tests for the WorkerSupervisor.
"""

import signal
import sys

from unittest import TestCase
from unittest.mock import MagicMock
from unittest.mock import patch

from neuro_san.service.main_loop.worker_supervisor import WorkerSupervisor


class TestWorkerSupervisor(TestCase):
    """
    Tests platform, worker identification, and process supervision logic.
    """

    @patch(
        "neuro_san.service.main_loop.worker_supervisor.sys.argv",
        ["server_main_loop", "--http_server_instances=1"],
    )
    def test_supervisor_is_not_used_for_one_instance(self):
        """Single-process startup does not need a supervisor."""
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(WorkerSupervisor.run(), -1)

    @patch(
        "neuro_san.service.main_loop.worker_supervisor.sys.argv",
        ["server_main_loop", "--http_server_instances=2"],
    )
    def test_supervisor_is_not_used_when_already_worker(self):
        """Worker processes should bypass the supervisor and run ServerMainLoop."""
        with patch.dict("os.environ", {WorkerSupervisor.WORKER_ENV: "1"}, clear=True):
            self.assertEqual(WorkerSupervisor.run(), -1)

    @patch(
        "neuro_san.service.main_loop.worker_supervisor.sys.argv",
        ["server_main_loop", "--http_server_instances=-1"],
    )
    def test_supervisor_raises_on_negative_instances(self):
        """Negative instances must raise a ValueError."""
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                WorkerSupervisor.run()

    @patch("neuro_san.service.main_loop.worker_supervisor.sys.platform", "win32")
    @patch(
        "neuro_san.service.main_loop.worker_supervisor.sys.argv",
        ["server_main_loop", "--http_server_instances=2"],
    )
    def test_supervisor_raises_on_windows_multi_instance(self):
        """Multi-instance startup on Windows raises NotImplementedError."""
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(NotImplementedError):
                WorkerSupervisor.run()

    @patch("neuro_san.service.main_loop.worker_supervisor.signal.signal")
    @patch("neuro_san.service.main_loop.worker_supervisor.subprocess.Popen")
    @patch(
        "neuro_san.service.main_loop.worker_supervisor.sys.orig_argv",
        ["python", "-m", "server_main_loop"],
    )
    @patch(
        "neuro_san.service.main_loop.worker_supervisor.sys.argv",
        ["server_main_loop", "--http_server_instances=2"],
    )
    @patch("neuro_san.service.main_loop.worker_supervisor.sys.platform", "linux")
    def test_supervisor_spawns_workers_on_posix(self, popen_mock, signal_mock):
        """Supervisor spawns fresh interpreters with worker identity env vars on POSIX."""
        popen_mock.return_value.__enter__.return_value = popen_mock.return_value
        popen_mock.return_value.poll.return_value = 0
        popen_mock.return_value.returncode = 0
        popen_mock.return_value.wait.return_value = 0

        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(WorkerSupervisor.run(), 0)

        self.assertEqual(popen_mock.call_count, 2)
        expected_worker_command = [sys.executable, "-m", "server_main_loop"]
        for idx, popen_call in enumerate(popen_mock.call_args_list):
            self.assertEqual(popen_call.args, (expected_worker_command,))
            env = popen_call.kwargs["env"]
            self.assertEqual(env[WorkerSupervisor.WORKER_ENV], "1")
            self.assertEqual(env[WorkerSupervisor.WORKER_ID_ENV], str(idx))
            self.assertEqual(env[WorkerSupervisor.NUM_WORKERS_ENV], "2")

        self.assertEqual(
            [signal_call.args[0] for signal_call in signal_mock.call_args_list],
            [signal.SIGINT, signal.SIGTERM],
        )
        self.assertEqual(signal_mock.call_args_list[0].args[1], WorkerSupervisor.stop_workers)
        self.assertEqual(signal_mock.call_args_list[1].args[1], WorkerSupervisor.stop_workers)

    def test_stop_workers_terminates_running_workers(self):
        """stop_workers should call terminate on running workers and skip exited ones."""
        running_worker = MagicMock()
        running_worker.poll.return_value = None
        exited_worker = MagicMock()
        exited_worker.poll.return_value = 0

        try:
            WorkerSupervisor.active_workers = [running_worker, exited_worker]
            WorkerSupervisor.stop_workers()
            running_worker.terminate.assert_called_once()
            exited_worker.terminate.assert_not_called()
        finally:
            WorkerSupervisor.active_workers = []

    def test_worker_identity_helpers(self):
        """Test is_worker(), get_worker_id(), and get_num_workers() with various env configurations."""
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(WorkerSupervisor.is_worker())
            self.assertEqual(WorkerSupervisor.get_worker_id(), 0)
            self.assertEqual(WorkerSupervisor.get_num_workers(), 1)

        custom_env = {
            WorkerSupervisor.WORKER_ENV: "1",
            WorkerSupervisor.WORKER_ID_ENV: "3",
            WorkerSupervisor.NUM_WORKERS_ENV: "8",
        }
        with patch.dict("os.environ", custom_env, clear=True):
            self.assertTrue(WorkerSupervisor.is_worker())
            self.assertEqual(WorkerSupervisor.get_worker_id(), 3)
            self.assertEqual(WorkerSupervisor.get_num_workers(), 8)

        invalid_env = {
            WorkerSupervisor.WORKER_ENV: "1",
            WorkerSupervisor.WORKER_ID_ENV: "not_a_number",
            WorkerSupervisor.NUM_WORKERS_ENV: "bad_number",
        }
        with patch.dict("os.environ", invalid_env, clear=True):
            self.assertTrue(WorkerSupervisor.is_worker())
            self.assertEqual(WorkerSupervisor.get_worker_id(), 0)
            self.assertEqual(WorkerSupervisor.get_num_workers(), 1)
