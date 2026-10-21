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


from argparse import Namespace
from unittest import TestCase
from unittest.mock import patch

from tests.load_tests.load_test_arguments import LoadTestArguments
from tests.load_tests.load_test_cli import LoadTestOrchestrator
from tests.load_tests.validation.input_validator import InputValidator
from tests.load_tests.validation.load_test_abort_error import LoadTestAbortError

DECLINED_EXIT_CODE: int = 0
FAILED_CHECK_EXIT_CODE: int = 1


class TestLoadTestAbortExit(TestCase):
    """
    Unit tests for LoadTestOrchestrator.main() and LoadTestAbortError.

    The validators raise LoadTestAbortError; main() is the one place that
    turns it into a process exit with the same exit code.
    """

    def test_failed_check_exits_with_code_one(self) -> None:
        """
        A validator check that fails while the orchestrator is built exits with code 1.
        """
        args: Namespace = Namespace(rebuild=None, trend=None, compare=None)
        abort_error = LoadTestAbortError(FAILED_CHECK_EXIT_CODE)
        with patch.object(LoadTestArguments, "parse_args", return_value=args), \
                patch.object(InputValidator, "validate_fixtures_hocon_dir", side_effect=abort_error), \
                self.assertRaises(SystemExit) as raised:
            LoadTestOrchestrator.main()
        self.assertEqual(raised.exception.code, FAILED_CHECK_EXIT_CODE)

    def test_declined_run_exits_with_code_zero(self) -> None:
        """
        An abort with exit code 0 (the user declined the run) exits with code 0.
        """
        args: Namespace = Namespace(rebuild=None, trend=None, compare=None)
        abort_error = LoadTestAbortError(DECLINED_EXIT_CODE)
        with patch.object(LoadTestArguments, "parse_args", return_value=args), \
                patch.object(InputValidator, "validate_fixtures_hocon_dir", side_effect=abort_error), \
                self.assertRaises(SystemExit) as raised:
            LoadTestOrchestrator.main()
        self.assertEqual(raised.exception.code, DECLINED_EXIT_CODE)
