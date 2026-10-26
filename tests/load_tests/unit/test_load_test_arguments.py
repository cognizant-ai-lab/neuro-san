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
from typing import List
from unittest import TestCase
from unittest.mock import patch

from tests.load_tests.load_test_arguments import LoadTestArguments


class TestLoadTestArguments(TestCase):
    """
    Unit tests for LoadTestArguments: the chat filter that --minimal selects.
    """

    def test_minimal_selects_the_minimal_chat_filter(self) -> None:
        """
        chat_filter is "maximal" by default and "minimal" with --minimal.
        """
        default_args: Namespace = TestLoadTestArguments._parse(["load_test_cli.py"])
        minimal_args: Namespace = TestLoadTestArguments._parse(["load_test_cli.py", "--minimal"])
        self.assertEqual("maximal", default_args.chat_filter)
        self.assertEqual("minimal", minimal_args.chat_filter)

    @staticmethod
    def _parse(argv: List[str]) -> Namespace:
        """
        Parse a load-test command line.

        :param argv: The command line, program name first
        :return: The parsed arguments
        """
        with patch("sys.argv", argv):
            return LoadTestArguments.parse_args("")
