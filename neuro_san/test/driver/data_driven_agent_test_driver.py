
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

import os
import shutil
from typing import Any
from typing import Dict
from typing import Generator
from typing import List
from typing import Union

from copy import copy
from datetime import datetime
from os import environ

from concurrent.futures import as_completed
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor

from leaf_common.config.file_of_class import FileOfClass
from leaf_common.parsers.dictionary_extractor import DictionaryExtractor
from leaf_common.persistence.easy.easy_hocon_persistence import EasyHoconPersistence
from leaf_common.time.timeout import Timeout

from neuro_san.client.agent_session_factory import AgentSessionFactory
from neuro_san.client.streaming_input_processor import StreamingInputProcessor
from neuro_san.interfaces.agent_session import AgentSession
from neuro_san.message_processing.basic_message_processor import BasicMessageProcessor
from neuro_san.session.direct_agent_session import DirectAgentSession
from neuro_san.test.driver.assert_capture import AssertCapture
from neuro_san.test.evaluators.agent_evaluator_factory import AgentEvaluatorFactory
from neuro_san.test.interfaces.agent_evaluator import AgentEvaluator
from neuro_san.test.interfaces.assert_forwarder import AssertForwarder


class DataDrivenAgentTestDriver:
    """
    Class which manages the execution of a single data-driven test case
    specified as a hocon file.
    """

    TEST_KEYS: List[str] = ["text", "structure", "sly_data"]

    def __init__(self, asserts: AssertForwarder, fixtures: FileOfClass = None, test_name: str = None):
        """
        Constructor
        :param asserts: The AssertForwarder instance to use to integrate failures
                        back into the test system.
        :param fixtures: Optional path to the fixtures root.
        """
        self.asserts_basis: AssertForwarder = asserts
        self.fixtures: FileOfClass = fixtures
        self.test_name: str = test_name

    # pylint: disable=too-many-locals
    def one_test(self, hocon_file: str):
        """
        Use a single hocon file in the fixtures as a test case"

        :param hocon_file: The name of the hocon from the fixtures directory.
        """
        test_case: Dict[str, Any] = self.parse_hocon_test_case(hocon_file)

        agent: str = test_case.get("agent")
        self.asserts_basis.assertIsNotNone(agent)

        # Set up any global test timeout.
        timeouts: List[Timeout] = []
        timeout_in_seconds: float = test_case.get("timeout_in_seconds", None)
        if timeout_in_seconds is not None:
            test_timeout = Timeout(name=agent)
            test_timeout.set_limit_in_seconds(timeout_in_seconds)
            timeouts.append(test_timeout)

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

        # Capture asserts for each iteration
        iteration_asserts: List[AssertCapture] = []

        # Loop through each iteration, capturing any asserts.
        num_successful: int = 0

        # Extract the second-to-last part of the path,the parent folder name.
        fixture_hocon_name = os.path.basename(os.path.dirname(hocon_file))

        # Loop through each test iteration in parallel
        with ThreadPoolExecutor(max_workers=num_iterations) as executor:

            futures: List[Future] = []
            for iteration_index in range(num_iterations):

                # Don't include an iteration index if there is only one iteration to do.
                if num_iterations == 1:
                    iteration_index = None

                future: Future = executor.submit(self.capture_one_iteration, test_case, timeouts,
                                                 fixture_hocon_name, iteration_index)
                futures.append(future)

            for future in as_completed(futures):
                assert_capture: AssertCapture = future.result()
                iteration_asserts.append(assert_capture)

                asserts: List[AssertionError] = assert_capture.get_asserts()
                if len(asserts) > 0:
                    # Not successful
                    continue

                num_successful += 1
                if num_successful == num_need_success:
                    # Don't look at more tests than we actually need to
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

        # Don't bother reporting any asserts if we have met our success ratio.
        # Return early to pass this test.
        if num_successful >= num_need_success:
            return

        # Find the first assert that fails and use it to fail this test
        for assert_capture in iteration_asserts:
            asserts: List[AssertionError] = assert_capture.get_asserts()
            if len(asserts) > 0:
                one_assert: AssertionError = asserts[0]
                message: str = f"""
{num_successful} of {num_iterations} iterations on agent {agent} were successful.
Need at least {num_need_success} to consider {hocon_file} test to be successful.
"""
                raise AssertionError(message) from one_assert

    def capture_one_iteration(self, test_case: Dict[str, Any], timeouts: List[Timeout],
                              fixture_hocon_name: str, iteration_index: int) -> AssertCapture:
        """

        :param test_case: The dictionary describing the data-driven test case
        :param timeouts: A list of timeout objects to check
        :param fixture_hocon_name: A string containing the name of the fixture hocon file
        :param iteration_index: The index of this test iteration for the success_ratio
        :return: An AssertCapture object for the iteration.
        """
        # Capture the asserts for this iteration and add it to the list for later
        assert_capture = AssertCapture(self.asserts_basis)

        # Perform a single iteration of the test.
        self.one_iteration(test_case, assert_capture, timeouts, fixture_hocon_name, iteration_index)

        return assert_capture

    # pylint: disable=too-many-locals, too-many-arguments, too-many-positional-arguments
    def one_iteration(self, test_case: Dict[str, Any], asserts: AssertForwarder,
                      timeouts: List[Timeout], fixture_hocon_name: str, iteration_index: int):
        """
        Perform a single iteration on the test case.

        :param test_case: The dictionary describing the data-driven test case
        :param asserts: The AssertForwarder to send asserts to.
        :param timeouts: A list of timeout objects to check
        :param fixture_hocon_name: A string containing the name of the fixture hocon file
        :param iteration_index: The index of this test iteration for the success_ratio
        """

        # Get the agent to use
        agent: str = test_case.get("agent")

        # Get the connection type
        connections: Union[List[str], str] = test_case.get("connections")
        if connections is None:
            # Assume direct if not specified
            connections = ["direct"]
        elif isinstance(connections, str):
            # Make single strings into a list for consistent parsing
            connections = [connections]
        asserts.assertIsInstance(connections, List)
        asserts.assertGreater(len(connections), 0)

        # Collect the interations to test for
        empty: List[Any] = []
        interactions: List[Dict[str, Any]] = test_case.get("interactions", empty)
        asserts.assertGreater(len(interactions), 0)

        # Collect other session information
        use_direct: bool = test_case.get("use_direct", False)
        timeout_in_seconds: float = test_case.get("timeout_in_seconds", None)
        metadata: Dict[str, Any] = test_case.get("metadata", None)
        if metadata is None:
            # Use a default from the user's environment to at least let
            # a server know who is doing the querying.
            metadata = {
                "user_id": environ.get("USER")
            }

        for connection in connections:

            session: AgentSession = AgentSessionFactory().create_session(
                    connection,
                    agent,
                    use_direct=use_direct,
                    metadata=metadata,
                    connect_timeout_in_seconds=timeout_in_seconds)
            chat_context: Dict[str, Any] = None
            # Track sly_data across interactions to allow accumulation and persistence
            carried_sly_data: Dict[str, Any] = None
            for interaction in interactions:

                if isinstance(session, DirectAgentSession):
                    session.reset()

                # interact() now returns a tuple of (chat_context, sly_data)
                # Both are carried forward to maintain multi-turn conversation state
                chat_context, carried_sly_data = self.interact(
                    agent,
                    session,
                    interaction,
                    chat_context,
                    asserts,
                    timeouts,
                    fixture_hocon_name,
                    iteration_index,
                    carried_sly_data
                )

    def parse_hocon_test_case(self, hocon_file: str) -> Dict[str, Any]:
        """
        Use a single hocon file in the fixtures as a test case"

        :param hocon_file: The name of the hocon from the fixtures directory.
        """
        test_path: str = hocon_file
        if self.fixtures is not None:
            test_path = self.fixtures.get_file_in_basis(hocon_file)
        hocon = EasyHoconPersistence(must_exist=True)
        test_case: Dict[str, Any] = hocon.restore(file_reference=test_path)
        return test_case

    # pylint: disable=too-many-locals,too-many-arguments,too-many-positional-arguments
    def interact(self, agent: str, session: AgentSession, interaction: Dict[str, Any],
                 chat_context: Dict[str, Any], asserts: AssertForwarder,
                 timeouts: List[Timeout], fixture_hocon_name: str, iteration_index: int,
                 sly_data: Dict[str, Any]) -> tuple:
        """
        Interact with an agent and evaluate its output

        :param session: The AgentSession to work with
        :param interaction: The interaction dictionary to base evalaution off of.
        :param chat_context: The chat context to use with the interaction (if any)
        :param asserts: The AssertForwarder to send asserts to.
        :param timeouts: A list of timeout objects to check
        :param fixture_hocon_name: A string containing the name of the fixture hocon file
        :param iteration_index: The index of this test iteration for the success_ratio
        :param sly_data: The sly_data from the previous interaction (if any)
        :return: A tuple of (chat_context, sly_data) to use in the next interaction
        """
        _ = agent       # For now
        empty: Dict[str, Any] = {}

        # Shallow copy what we already have in timeouts
        use_timeouts: List[Timeout] = copy(timeouts)

        # Prepare the processor
        thinking_dir: str = self._setup_thinking_dir(
            fixture_hocon_name=fixture_hocon_name,
            iteration_index=iteration_index,
        )

        input_processor = StreamingInputProcessor(session=session, thinking_dir=thinking_dir,
                                                  thinking_file="")
        processor: BasicMessageProcessor = input_processor.get_message_processor()

        # Prepare the request
        text: str = interaction.get("text")
        current_sly_data: str = interaction.get("sly_data")
        # Use current interaction's sly_data if provided, otherwise use carried-over sly_data
        # from the previous interaction. This allows sly_data to accumulate across turns.
        if current_sly_data is None:
            current_sly_data = sly_data

        # By having level to MINIMAL avoid unnecesssary thinking file(s) created.
        # MAXIMAL set to have thinking files.
        default_chat_filter: str = "MINIMAL"
        if thinking_dir is not None:
            default_chat_filter: str = "MAXIMAL"

        chat_filter: Dict[str, Any] = {
            "chat_filter_type": interaction.get("chat_filter", default_chat_filter)
        }

        request: Dict[str, Any] = input_processor.formulate_chat_request(
            text,
            current_sly_data,
            chat_context,
            chat_filter
        )

        # Prepare any interaction timeout
        if interaction.get("timeout_in_seconds") is not None:
            interaction_timeout = Timeout(name=text)
            interaction_timeout.set_limit_in_seconds(interaction.get("timeout_in_seconds"))
            use_timeouts.append(interaction_timeout)

        # Call streaming_chat()
        chat_responses: Generator[Dict[str, Any], None, None] = session.streaming_chat(request)
        for chat_response in chat_responses:
            message = chat_response.get("response", empty)
            processor.process_message(message, chat_response.get("type"))
            self.check_timeouts(use_timeouts)

        self.check_timeouts(use_timeouts)

        # Evaluate response
        response: Dict[str, Any] = interaction.get("response", empty)
        response_extractor = DictionaryExtractor(response)
        self.test_response_keys(processor, response_extractor, self.TEST_KEYS, asserts, use_timeouts)
        self.check_timeouts(use_timeouts)

        # See how we should continue the conversation
        return_chat_context: Dict[str, Any] = None
        return_sly_data: Dict[str, Any] = None
        if interaction.get("continue_conversation", True):
            return_chat_context = processor.get_chat_context()
            returned_sly_data: Dict[str, Any] = processor.get_sly_data()
            # Delegate merge logic to helper to keep this method concise
            return_sly_data = self._merge_sly_data(current_sly_data, returned_sly_data)
        else:
            return_sly_data = current_sly_data

        return return_chat_context, return_sly_data

    def test_response_keys(self, processor: BasicMessageProcessor,
                           response_extractor: DictionaryExtractor,
                           keys: List[str],
                           asserts: AssertForwarder,
                           timeouts: List[Timeout]):
        """
        Tests the given response keys

        :param processor: The BasicMessageProcessor instance to query results from.
        :param response_extractor: The DictionaryExtractor for the test structure from the test hocon file.
        :param keys: The response keys to test
        :param asserts: The AssertForwarder to send asserts to.
        :param timeouts: A list of timeout objects to check
        """
        deeper_test_keys: List[str] = []

        for test_key in keys:

            test_key_value: Dict[str, Any] = response_extractor.get(test_key)
            if test_key_value is None:
                # Got nothing for test_key. Nothing to see here. Please move along.
                continue

            if isinstance(test_key_value, Dict):
                # The value refers to a deeper dictionary test
                for deeper_key in test_key_value.keys():
                    deeper_test_keys.append(f"{test_key}.{deeper_key}")
            else:
                # The last part of the test_key refers to a specific evaluator type.
                split: List[str] = test_key.split(".")
                evaluator_type: str = split[-1]            # Last component of .-delimited key
                verify_key: str = ".".join(split[:-1])      # All but last component of .-delimited key
                evaluator: AgentEvaluator = AgentEvaluatorFactory.create_evaluator(asserts,
                                                                                   evaluator_type)
                if evaluator is not None:
                    evaluator.evaluate(processor, verify_key, test_key_value)
                    self.check_timeouts(timeouts)

        # Recurse if there are further dictionary specs to dive into
        if len(deeper_test_keys) > 0:
            self.test_response_keys(processor, response_extractor, deeper_test_keys, asserts, timeouts)

    def check_timeouts(self, timeouts: List[Timeout]):
        """
        :param timeouts: A list of timeout objects to check
        """
        for one_timeout in timeouts:
            Timeout.check_if_not_none(one_timeout)

    def _merge_sly_data(self, current_sly_data: Dict[str, Any],
                        returned_sly_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge sly_data returned from the agent into the current sly_data.

        Strategy:
        - If `returned_sly_data` is not None:
          - If `current_sly_data` exists, update it with the returned data and return it (accumulate).
          - Otherwise, return a shallow copy of `returned_sly_data`.
        - If `returned_sly_data` is None, return `current_sly_data` unchanged.

        :param current_sly_data: sly_data carried from previous interaction (may be None)
        :param returned_sly_data: sly_data returned by the processor (may be None)
        :return: merged sly_data dictionary or None
        """
        if returned_sly_data is not None:
            if current_sly_data is not None:
                current_sly_data.update(returned_sly_data)
                return current_sly_data
            return returned_sly_data.copy()
        return current_sly_data

    def _setup_thinking_dir(
        self,
        fixture_hocon_name: str,
        iteration_index: int,
    ) -> str:
        """
        Set up the thinking directory for this interaction, if configured.

        This method constructs a unique per-interaction directory under the path
        specified by the AGENT_TEST_THINKING_BASIS environment variable. The directory
        name incorporates a timestamp, the test name (or fixture hocon name as a
        fallback), and the iteration index to improve traceability across test runs.

        If AGENT_TEST_THINKING_BASIS is not set or is empty, no directory is created
        and None is returned.

        :param fixture_hocon_name: A string containing the name of the fixture hocon file
        :param iteration_index: The index of this test iteration for the success_ratio
        :return: The path to the created thinking directory, or None if not configured
        """
        # Prepare the processor
        thinking_dir: str = None

        # A reasonable default here is basis_dir = "/tmp/agent_test", but we
        # don't want to write thinking files out if no one wants them.
        basis_dir: str = os.environ.get("AGENT_TEST_THINKING_BASIS")
        if basis_dir is not None and len(basis_dir) > 0:
            now = datetime.now()
            datestr: str = now.strftime("%Y-%m-%d_%H-%M-%S")

            # Add a test name to thinking_dir
            # for better uniqueness and traceability across different test fixtures.
            use_name: str = self.test_name
            if use_name is None:
                use_name: str = fixture_hocon_name

            # Add iteration index for uniqueness
            index_suffix: str = ""
            if iteration_index is not None:
                index_suffix = f"_{iteration_index}"

            thinking_dir = f"{basis_dir}/{datestr}_{use_name}{index_suffix}"

            # Remove any contents that might be there already.
            # Writing over existing dir will just confuse output.
            # Although it is unlikely that two tests run at the same time...
            if os.path.exists(thinking_dir):
                shutil.rmtree(thinking_dir)
            # Create the directory anew
            os.makedirs(thinking_dir)

        return thinking_dir
