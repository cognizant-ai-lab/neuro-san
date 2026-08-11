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
Unit tests for the macOS worker supervisor.
"""

import signal
import sys

from unittest.mock import patch

from neuro_san.service.main_loop.macos_worker_supervisor import MacOsWorkerSupervisor


class TestMacOsWorkerSupervisor:
    """
    Tests platform and process-count selection without starting a service.
    """

    @patch("neuro_san.service.main_loop.macos_worker_supervisor.sys.platform", "linux")
    def test_supervisor_is_not_used_outside_macos(self):
        """Other platforms retain the existing Tornado worker flow."""
        assert MacOsWorkerSupervisor.run() == -1

    @patch("neuro_san.service.main_loop.macos_worker_supervisor.sys.platform", "darwin")
    @patch(
        "neuro_san.service.main_loop.macos_worker_supervisor.sys.argv",
        ["server_main_loop", "--http_server_instances=1"],
    )
    def test_supervisor_is_not_used_for_one_macos_instance(self):
        """Single-process macOS startup does not need a supervisor."""
        with patch.dict("os.environ", {}, clear=True):
            assert MacOsWorkerSupervisor.run() == -1

    @patch("neuro_san.service.main_loop.macos_worker_supervisor.signal.signal")
    @patch("neuro_san.service.main_loop.macos_worker_supervisor.subprocess.Popen")
    @patch(
        "neuro_san.service.main_loop.macos_worker_supervisor.sys.orig_argv",
        ["python", "-m", "server_main_loop"],
    )
    @patch(
        "neuro_san.service.main_loop.macos_worker_supervisor.sys.argv",
        ["server_main_loop", "--http_server_instances=2"],
    )
    @patch("neuro_san.service.main_loop.macos_worker_supervisor.sys.platform", "darwin")
    def test_supervisor_starts_fresh_macos_workers(self, popen, signal_mock):
        """Each macOS worker is a new interpreter sharing the configured port."""
        popen.return_value.__enter__.return_value = popen.return_value
        popen.return_value.poll.return_value = 0
        popen.return_value.returncode = 0
        popen.return_value.wait.return_value = 0

        with patch.dict("os.environ", {}, clear=True):
            assert MacOsWorkerSupervisor.run() == 0

        assert popen.call_count == 2
        for popen_call in popen.call_args_list:
            assert popen_call.args == ([sys.executable, "-m", "server_main_loop"],)
            assert popen_call.kwargs["env"][MacOsWorkerSupervisor.WORKER_ENV] == "1"
        assert [signal_call.args[0] for signal_call in signal_mock.call_args_list] == [
            signal.SIGINT,
            signal.SIGTERM,
        ]
