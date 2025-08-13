
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

from neuro_san.message_processing.basic_message_processor import BasicMessageProcessor


class AgentEvaluator:
    """
    Interface definition for evaluating part of an agent's response
    """

    def evaluate(self, processor: BasicMessageProcessor, test_key: str, verify_for: Any):
        """
        Evaluate the contents of the BasicMessageProcessor

        :param processor: The BasicMessageProcessor to evaluate
        :param test_key: the compound .-delimited key of the response value to test
        :param verify_for: The data to evaluate the response against
        """
        raise NotImplementedError
