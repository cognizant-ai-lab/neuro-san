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
from unittest import TestCase

from tests.load_tests.reporting.run_namer import RunNamer


class TestRunNamer(TestCase):
    """
    Tests for RunNamer: the run folder name from timestamp, host, neuro-san version and request count.
    """

    def test_run_folder_name_with_version(self) -> None:
        """
        The folder name has the timestamp, the host, "ns" plus the version, and the count.
        """
        folder_name: str = RunNamer.run_folder_name("20261020_224538", "localhost", "0.6.92", 2)
        self.assertEqual(folder_name, "20261020_224538_localhost_ns0.6.92_2")

    def test_run_folder_name_without_version(self) -> None:
        """
        Without a version the folder name leaves out the version part.
        """
        folder_name: str = RunNamer.run_folder_name("20261020_224538", "localhost", None, 5)
        self.assertEqual(folder_name, "20261020_224538_localhost_5")

    def test_run_folder_name_replaces_unsafe_characters(self) -> None:
        """
        Characters other than letters, digits, ".", "+" and "-" in the host and version become "-".
        """
        folder_name: str = RunNamer.run_folder_name("20261020_224538", "my_host:8080", "0.6.92 dev/1", 3)
        self.assertEqual(folder_name, "20261020_224538_my-host-8080_ns0.6.92-dev-1_3")
