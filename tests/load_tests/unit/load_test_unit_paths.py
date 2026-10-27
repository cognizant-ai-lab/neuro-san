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

from os.path import join

from neuro_san import TOP_LEVEL_DIR
from tests.load_tests.load_test_constants import LoadTestConstants


class LoadTestUnitPaths:
    """
    Paths shared by the load-test unit tests. The module and class names keep pytest from collecting them,
    and importing this class does not run any test class again.
    """

    # The neuro-san project root, the folder above the neuro_san package.
    PROJECT_ROOT: str = TOP_LEVEL_DIR.get_file_in_basis("..")
    # The load-test fixtures folder, with one subfolder of test-case hocon files per agent.
    FIXTURES_HOCON_DIR: str = join(PROJECT_ROOT, LoadTestConstants.DEFAULT_FIXTURES_HOCON_DIR)
