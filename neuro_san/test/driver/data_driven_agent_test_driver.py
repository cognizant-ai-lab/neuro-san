
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

from typing import Any
from typing import Dict
from typing import List

from leaf_common.config.file_of_class import FileOfClass

from neuro_san.test.driver.data_driven_tests_driver import DataDrivenTestsDriver
from neuro_san.test.driver.timed_assert_capture import TimedAssertCapture
from neuro_san.test.util.tests_util import TestsUtil
from neuro_san.test.interfaces.assert_forwarder import AssertForwarder


class DataDrivenAgentTestDriver:
    """
    Class which manages the execution of a single data-driven test case
    specified as a hocon file.
    """

    def __init__(self, asserts: AssertForwarder, fixtures: FileOfClass = None, test_name: str = None):
        """
        Constructor
        :param asserts: The AssertForwarder instance to use to integrate failures
                        back into the test system.
        :param fixtures: Optional path to the fixtures root.
        :param test_name: Optional name of the test case for logging and reporting.
        """
        self.asserts_basis: AssertForwarder = asserts
        self.fixtures: FileOfClass = fixtures
        self.test_name: str = test_name
        self.test_driver:  DataDrivenTestsDriver = DataDrivenTestsDriver(asserts, self.test_name)

    # pylint: disable=too-many-locals
    def one_test(self, hocon_file: str):
        """
        Use a single hocon file in the fixtures as a test case

        :param hocon_file: The name of the hocon from the fixtures directory.
        """
        test_case: Dict[str, Any] = TestsUtil.parse_hocon_test_case(self.fixtures, hocon_file)

        agent: str = test_case.get("agent")
        self.asserts_basis.assertIsNotNone(agent)

        # Get the success ratio
        success_ratio: str = test_case.get("success_ratio", "1/1")
        self.asserts_basis.assertIn("/", success_ratio)

        # Find the integer components of the success ratio
        success_split: List[str] = success_ratio.split("/")
        num_need_success: int = int(success_split[0])
        num_iterations: int = int(success_split[-1])

        # Put some bounds on the number of iterations
        num_iterations = max(1, num_iterations)
        num_need_success = min(num_need_success, num_iterations)

        # Construct a collection of tests we want to run.
        # In this case, we will run the same test multiple times in parallel.
        tests: List[Dict[str, Any]] = [test_case] * num_iterations

        # Capture test results for each iteration
        test_results: List[TimedAssertCapture] = self.test_driver.run_tests(tests, num_need_success)

        # First check if we have met our success ratio. If so, return early to pass this test.
        num_successful: int = 0
        for test_result in test_results:
            # Test result is successful if it has no asserts captured.
            if len(test_result.get_asserts()) == 0:
                num_successful += 1
                if num_successful >= num_need_success:
                    return

        # If we have not met our success ratio, we will report the first assert that failed.
        for test_result in test_results:
            asserts: List[AssertionError] = test_result.get_asserts()
            if len(asserts) > 0:
                one_assert: AssertionError = asserts[0]
                message: str = f"""
{num_successful} of {num_iterations} iterations on agent {agent} were successful.
Need at least {num_need_success} to consider {hocon_file} test to be successful.
"""
                raise AssertionError(message) from one_assert
