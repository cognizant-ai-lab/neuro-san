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

from tests.load_tests.monitoring.resource_monitor import ResourceMonitor


class TestResourceMonitor(TestCase):
    """
    Unit tests for ResourceMonitor: CPU cores in use.
    """

    def test_cores_in_use(self) -> None:
        """
        A whole-system CPU percentage becomes the number of cores it keeps busy.
        """
        half_of_four: float = ResourceMonitor.cores_in_use(50.0, 4)
        none_of_eight: float = ResourceMonitor.cores_in_use(0.0, 8)

        self.assertEqual(2.0, half_of_four)
        self.assertEqual(0.0, none_of_eight)
