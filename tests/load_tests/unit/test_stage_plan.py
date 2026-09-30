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
Unit tests for StagePlan.
"""

from unittest import TestCase

from tests.load_tests.traffic.stage_plan import StagePlan


class TestStagePlan(TestCase):
    """
    StagePlan hands back exactly what it was built with.
    """

    def test_getters_return_constructor_values(self) -> None:
        """
        Each getter returns its constructor argument.
        """
        plan: StagePlan = StagePlan(5, 3, 11, "/tmp/stage-1")
        self.assertEqual(5, plan.get_num_requests())
        self.assertEqual(3, plan.get_max_workers())
        self.assertEqual(11, plan.get_global_offset())
        self.assertEqual("/tmp/stage-1", plan.get_output_dir())

    def test_output_dir_may_be_none(self) -> None:
        """
        A stage without an output directory keeps None.
        """
        self.assertIsNone(StagePlan(1, 1, 0, None).get_output_dir())
