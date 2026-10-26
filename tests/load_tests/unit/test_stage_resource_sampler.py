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
from typing import Dict
from unittest import TestCase

from tests.load_tests.monitoring.progress_log_writer import ProgressLogWriter
from tests.load_tests.monitoring.stage_resource_sampler import StageResourceSampler


class TestStageResourceSampler(TestCase):
    """
    Unit tests for StageResourceSampler: its peaks and its readings without server or client process.
    """

    def test_peaks_ignore_zero_and_lower_readings(self) -> None:
        """
        A peak is only kept for a reading above zero and above the peak so far.
        """
        self.assertFalse(StageResourceSampler.is_new_peak(0, None))
        self.assertTrue(StageResourceSampler.is_new_peak(5, None))
        self.assertFalse(StageResourceSampler.is_new_peak(5, 5))
        self.assertTrue(StageResourceSampler.is_new_peak(6.5, 5))

    def test_no_process_gives_no_server_readings(self) -> None:
        """
        Without a server process, the server is taken as alive and its progress line parts are empty.
        """
        writer: ProgressLogWriter = ProgressLogWriter(None)
        sampler: StageResourceSampler = StageResourceSampler(None, None, writer)
        sampler.sample_client_rss()
        server_alive: bool = sampler.check_server_alive()
        server_metrics: Dict[str, str] = sampler.sample_server_metrics()
        expected_metrics: Dict[str, str] = {
            "thread_info": "",
            "server_rss_info": "",
        }
        self.assertTrue(server_alive)
        self.assertEqual(expected_metrics, server_metrics)
        self.assertIsNone(sampler.get_peak_server_threads())
        self.assertIsNone(sampler.get_peak_client_rss_megabytes())
        self.assertIsNone(sampler.get_peak_server_rss_megabytes())

    def test_system_readings_keep_their_peaks(self) -> None:
        """
        The system CPU, memory and thread readings each leave a peak.
        """
        writer: ProgressLogWriter = ProgressLogWriter(None)
        sampler: StageResourceSampler = StageResourceSampler(None, None, writer)
        cpu_text: str = sampler.format_system_cpu()
        memory_text: str = sampler.system_memory_info()
        sampler.sample_system_threads()
        self.assertIn("syscpu:", cpu_text)
        self.assertNotEqual("", memory_text)
        self.assertIsNotNone(sampler.get_peak_system_cpu_percent())
        self.assertIsNotNone(sampler.get_peak_system_memory())
        self.assertIsNotNone(sampler.get_peak_system_threads())
