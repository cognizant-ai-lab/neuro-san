
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

from neuro_san.test.evaluators.abstract_agent_evaluator import AbstractAgentEvaluator


class GreaterAgentEvaluator(AbstractAgentEvaluator):
    """
    AbstractAgentEvaluator implementation that looks for inequalities of values in output.
    """

    def test_one(self, verify_value: Any, test_value: Any):
        """
        :param verify_value: The value to verify against
        :param test_value: The value appearing in the test sample
        """
        if self.negate:
            self.asserts.assertLessEqual(verify_value, test_value)
        else:
            self.asserts.assertGreater(verify_value, test_value)
