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

from tests.load_tests.reporting.system_resources import SystemResources

# pylint: disable=protected-access


class TestSystemResources(TestCase):
    """
    Unit tests for SystemResources._format_memory_row(): the memory row with and without the free memory.
    """

    def test_memory_row_with_free_memory(self) -> None:
        """
        A snapshot with the free memory gives used, free and percent.
        """
        row_text: str = SystemResources._format_memory_row({"memory_percent": 50.0, "available_gigabytes": 7.5}, 16.0)

        self.assertEqual("8192 MB used / 7.5 GB free (50% used)", row_text)

    def test_memory_row_without_free_memory(self) -> None:
        """
        A snapshot whose free memory is None gives 'n/a free' instead of raising TypeError.
        """
        row_text: str = SystemResources._format_memory_row({"memory_percent": 50.0, "available_gigabytes": None}, 16.0)

        self.assertEqual("8192 MB used / n/a free (50% used)", row_text)
