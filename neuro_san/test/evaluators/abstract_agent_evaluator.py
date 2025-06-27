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
from typing import List
from typing import Dict

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.message_processing.basic_message_processor import BasicMessageProcessor
from neuro_san.test.interfaces.agent_evaluator import AgentEvaluator
from neuro_san.test.interfaces.assert_forwarder import AssertForwarder


class AbstractAgentEvaluator(AgentEvaluator):
    """
    Abstract AgentEvaluator implementation that does common preparation for tests
    """

    def __init__(self, asserts: AssertForwarder, negate: bool = False):
        """
        Constructor

        :param asserts: The AssertForwarder instance to handle failures
        :param negate: If true the verification criteria should be negated
        """
        self.asserts: AssertForwarder = asserts
        self.negate: bool = negate

    def evaluate(self, processor: BasicMessageProcessor, test_key: str, verify_for: Any):
        """
        Evaluate the contents of the BasicMessageProcessor

        :param processor: The BasicMessageProcessor to evaluate
        :param test_key: the compound .-delimited key of the response value to test
        :param verify_for: The data to evaluate the response against
        """

        split: str = test_key.split(".")
        first_component: str = split[0]

        # Make a dictionary out of what we want to test
        test_dict: Dict[str, Any] = {}
        if first_component == "text":
            test_dict[first_component] = processor.get_answer()
        elif first_component == "structure":
            test_dict[first_component] = processor.get_structure()
        elif first_component == "sly_data":
            test_dict[first_component] = processor.get_sly_data()

        # Get the value we want to test out of that dictionary
        extractor = DictionaryExtractor(test_dict)
        test_value: Any = extractor.get(test_key)
        self.asserts.assertIsNotNone(test_value, f"{test_key} is None")

        # Prepare a list of keywords to verify
        verify_all: List[Any] = verify_for
        if not isinstance(verify_for, List):
            verify_all = [verify_for]
        self.asserts.assertIsInstance(verify_all, List)

        # Be sure everything specified to test for is in there... or not
        for verify_one in verify_all:
            self.test_one(verify_one, test_value)

    def test_one(self, verify_value: Any, test_value: Any):
        """
        Subclasses override this with the details of how they are testing
        the test_value from the test instance against the constancy of the verify_value.

        :param verify_value: The value to verify against
        :param test_value: The value appearing in the test sample
        """
        raise NotImplementedError
