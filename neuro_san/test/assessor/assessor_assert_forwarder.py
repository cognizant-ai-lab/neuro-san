
# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT
from typing import Any
from typing import Dict
from typing import List

from neuro_san.test.interfaces.null_assert_forwarder import NullAssertForwarder


class AssessorAssertForwarder(NullAssertForwarder):
    """
    AssertForwarder implemetation for the agent Assessor.

    This guy generally does not care about the correctness of the asserts themselves,
    but serves to collect failure data for the Assessor.
    """

    def __init__(self):
        """
        Constructor
        """
        self.num_total: int = 0
        self.fail: List[Dict[str, Any]] = []

    def get_num_total(self) -> int:
        """
        :return: The total number of test cases seen
        """
        return self.num_total

    def get_fail_dicts(self) -> List[Dict[str, Any]]:
        """
        :return: The failure dictionaries for further analysis
        """
        return self.fail

    # pylint: disable=invalid-name
    def assertGist(self, gist: bool, acceptance_criteria: str, text_sample: str, msg: str = None):
        """
        Assert that the gist is true

        :param gist: Pass/Fail value of the gist expected to be True
        :param acceptance_criteria: The value to verify against
        :param text_sample: The value appearing in the test sample
        :param msg: optional string message
        """
        self.handle_assert(gist, acceptance_criteria, text_sample, True)

    # pylint: disable=invalid-name
    def assertNotGist(self, gist: bool, acceptance_criteria: str, text_sample: str, msg: str = None):
        """
        Assert that the gist is true

        :param gist: Pass/Fail value of the gist expected to be False
        :param acceptance_criteria: The value to verify against
        :param text_sample: The value appearing in the test sample
        :param msg: optional string message
        """
        self.handle_assert(gist, acceptance_criteria, text_sample, False)

    def handle_assert(self, is_passing: bool,
                      acceptance_criteria: str,
                      text_sample: str,
                      sense: bool):
        """
        Handle the assert.
        :param is_passing: Boolean as to whether or not the test is passing.
        :param acceptance_criteria: The value to verify against
        :param text_sample: The value appearing in the test sample
        :param sense: Whether the test was supposed to be true or false.
        """
        self.num_total += 1
        if is_passing == sense:
            return

        components: Dict[str, Any] = {
            "acceptance_criteria": acceptance_criteria,
            "text_sample": text_sample,
            "sense": sense
        }
        self.fail.append(components)
