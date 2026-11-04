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

from os.path import abspath
from os.path import dirname

from leaf_common.logging.logging_setup import LoggingSetup

from tests.load_tests.load_test_constants import LoadTestConstants


class LoadTestLogging:
    """
    Console logging setup shared by both load-test CLIs.
    """

    @staticmethod
    def setup() -> None:
        """
        Set up console logging from tests/load_tests/logging.hocon, next to this file.
        """
        this_file: str = abspath(__file__)
        config_dir: str = dirname(this_file)
        logging_setup: LoggingSetup = LoggingSetup(default_log_config_dir=config_dir,
                                                   default_log_config_file=LoadTestConstants.LOGGING_CONFIG_FILE,
                                                   default_log_level="INFO")
        logging_setup.setup()
