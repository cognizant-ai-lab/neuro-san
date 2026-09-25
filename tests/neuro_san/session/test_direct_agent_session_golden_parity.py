
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
from typing import Optional

from copy import deepcopy
from json import dumps
from json import loads
from os import environ
from threading import active_count
from time import monotonic
from time import sleep
from unittest import TestCase

from leaf_common.asyncio.asyncio_executor_pool import AsyncioExecutorPool
from leaf_common.config.file_of_class import FileOfClass

from neuro_san import REGISTRIES_DIR
from neuro_san.internals.graph.persistence.agent_network_restorer import AgentNetworkRestorer
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.context_type_llm_factory import ContextTypeLlmFactory
from neuro_san.internals.interfaces.context_type_toolbox_factory import ContextTypeToolboxFactory
from neuro_san.internals.run_context.factory.master_llm_factory import MasterLlmFactory
from neuro_san.internals.run_context.factory.master_toolbox_factory import MasterToolboxFactory
from neuro_san.message.processors.basic_message_processor import BasicMessageProcessor
from neuro_san.session.direct_agent_session import DirectAgentSession
from neuro_san.session.external_agent_session_factory import ExternalAgentSessionFactory
from neuro_san.session.session_invocation_context import SessionInvocationContext


class TestDirectAgentSessionGoldenParity(TestCase):
    """
    Golden-parity test for the client-visible wire stream of a whole request.

    Issue #1222 made the in-server message pipeline safe for LangChain content
    blocks (reasoning, multiple text blocks, data blocks) while promising that
    the dicts a client receives for ordinary text traffic do not change at all.
    The converter and journal tests each lock one layer of that promise. This
    test locks the composition: it drives the chat_mock_llm_echo network through
    DirectAgentSession.streaming_chat with the MAXIMAL filter, so nothing the
    network emits is filtered out, and compares the complete stream of response
    dicts against a golden file checked into tests/neuro_san/session/golden.

    The network is a single front man with no tools, so the streams hold the
    SYSTEM (first turn only, when the history is empty), HUMAN, AI, AGENT token
    accounting and AGENT_FRAMEWORK answer messages. Tool results, sub-agent
    origins, error frames, sly_data and structure parsing are not exercised here
    and would need a tool-calling mock network.

    Four conversations are locked:

    * a plain two-turn echo, which carries chat_context from the first turn into
      the second, so the history round trip is covered as well. This golden also
      passes on main as it was before the first #1222 PR (7fbebb1b), which is
      the byte-identical guarantee the issue asked for;
    * a single turn using the mock's "emit anthropic thinking:" marker, which makes the mock
      answer with an Anthropic-style thinking block ahead of the text, so the
      golden shows that block content arriving at the converter reaches the wire
      as the text alone. The wire stays text-only in Phase 1; the journal side of
      that answer is covered by test_originating_journal;
    * the same for the mock's "emit openai reasoning:" marker, which imitates a
      ChatOpenAI Responses API reply with reasoning summaries, a different raw
      shape (reasoning item with id, summary parts and encrypted content, then
      a text item) that must flatten to the same text-only wire;
    * the same for the mock's "emit gemini thinking:" marker, which imitates a
      ChatGoogleGenerativeAI reply from Gemini 3 with include_thoughts on, where
      the thinking block carries no signature and the text block carries the
      thought signature in its extras, the third raw shape that must flatten to
      the same text-only wire.

    The only volatile fields in the stream are the time_taken_in_seconds values
    in the token accounting messages; those are zeroed before comparing. Empty
    dicts are keep-alive frames from the sync generator and carry no content, so
    they are dropped.

    Each conversation also checks that no thread outlives the session: the pool
    shuts an executor down when the session returns it, so the thread count must
    be back where it started once the session is closed. A reused session that
    did not run finish_request() for a later turn would fail this check.

    To regenerate the golden files after an intended wire change, run the test
    with NEURO_SAN_UPDATE_GOLDEN=1. That run rewrites the files and reports the
    tests as skipped, so it can never pass by comparing a file with itself;
    review the diff, then run again without the variable.
    """

    # Registry hocon of the mock network under test. It has no tools and no
    # external agents, so no provider key or network access is needed.
    AGENT_HOCON: str = "chat_mock_llm_echo.hocon"

    # Locates the golden files relative to this module.
    GOLDEN_DIR: FileOfClass = FileOfClass(__file__, path_to_basis="golden")

    # The one key whose value depends on wall-clock time.
    VOLATILE_KEY: str = "time_taken_in_seconds"

    # Set this environment variable to rewrite the golden files from the current run.
    UPDATE_ENV_VAR: str = "NEURO_SAN_UPDATE_GOLDEN"

    def setUp(self) -> None:
        """
        Shows full diffs when a golden comparison fails.
        """
        self.maxDiff = None  # pylint: disable=invalid-name

    def create_session(self) -> DirectAgentSession:
        """
        Builds a DirectAgentSession for the mock network without reading the
        registry manifest. Reading the manifest parses every registry hocon in a
        thread pool, which is slow and is not what this test is about.

        :return: A started DirectAgentSession for the chat_mock_llm_echo network.
        """
        file_reference: str = REGISTRIES_DIR.get_file_in_basis(self.AGENT_HOCON)
        agent_network: AgentNetwork = AgentNetworkRestorer().restore(file_reference=file_reference)
        config: Dict[str, Any] = agent_network.get_config()

        llm_factory: ContextTypeLlmFactory = MasterLlmFactory.create_llm_factory(config)
        toolbox_factory: ContextTypeToolboxFactory = MasterToolboxFactory.create_toolbox_factory(config)
        # Keep the test hermetic: neither a user llm info file (it could price the
        # mock model and change total_cost) nor a user toolbox info file from the
        # environment may take part.
        if hasattr(llm_factory, "llm_info_file"):
            llm_factory.llm_info_file = None
        if hasattr(toolbox_factory, "toolbox_info_file"):
            toolbox_factory.toolbox_info_file = None
        llm_factory.load()
        toolbox_factory.load()

        # No external agents in this network, so the external session factory
        # never needs network storage.
        external_factory = ExternalAgentSessionFactory(use_direct=True, network_storage_dict=None)
        # reuse_mode=False: the pool then starts no garbage-collection thread and
        # shuts each executor down when the session returns it, so a conversation
        # leaves no threads behind for the rest of the suite.
        invocation_context = SessionInvocationContext(self.AGENT_HOCON,
                                                      external_factory,
                                                      AsyncioExecutorPool(reuse_mode=False),
                                                      llm_factory,
                                                      toolbox_factory)
        invocation_context.start()
        return DirectAgentSession(agent_network=agent_network, invocation_context=invocation_context)

    def run_conversation(self, turns: List[str]) -> List[Dict[str, Any]]:
        """
        Sends the turns through one session as a single conversation and
        collects every response dict the client would receive.

        :param turns: The user inputs, in order.
        :return: The normalized stream of response dicts across all turns.
        """
        threads_before: int = active_count()
        session: DirectAgentSession = self.create_session()
        stream: List[Dict[str, Any]] = []
        chat_context: Optional[Dict[str, Any]] = None
        try:
            for turn in turns:
                # Same protocol as the smoke test driver: reset the direct
                # session before each turn and carry the chat_context forward.
                session.reset()
                request: Dict[str, Any] = {
                    "user_message": {"text": turn},
                    "chat_filter": {"chat_filter_type": "MAXIMAL"},
                }
                if chat_context is not None:
                    request["chat_context"] = chat_context
                processor = BasicMessageProcessor()
                for response in session.streaming_chat(request):
                    if not response:
                        # Keep-alive frame from the sync generator; timing dependent, no content.
                        continue
                    stream.append(response)
                    message: Dict[str, Any] = response.get("response")
                    processor.process_message(message, message.get("type"))
                chat_context = processor.get_chat_context()
        finally:
            session.close()
        # The pool shuts each returned executor down and joins its thread, so a
        # thread that is still alive here belongs to a turn whose finish_request()
        # never ran and whose executor was therefore never returned.
        self.assertLessEqual(self.wait_for_thread_count(threads_before), threads_before,
                             "a turn's executor thread outlived the session")
        return self.normalize(stream)

    @staticmethod
    def wait_for_thread_count(limit: int, timeout_seconds: float = 2.0) -> int:
        """
        Waits briefly for the thread count to fall to the given limit, since an
        executor's thread finishes a moment after the pool shuts it down.

        :param limit: The thread count to wait for.
        :param timeout_seconds: How long to keep checking before giving up.
        :return: The last thread count observed.
        """
        deadline: float = monotonic() + timeout_seconds
        count: int = active_count()
        while count > limit and monotonic() < deadline:
            sleep(0.05)
            count = active_count()
        return count

    @staticmethod
    def normalize(stream: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Produces a copy of the stream with every volatile value replaced by a constant.

        :param stream: The response dicts as received.
        :return: A deep copy with each time_taken_in_seconds set to 0.0.
        """
        normalized: List[Dict[str, Any]] = deepcopy(stream)
        for response in normalized:
            TestDirectAgentSessionGoldenParity.zero_volatile(response)
        return normalized

    @staticmethod
    def zero_volatile(node: Any) -> None:
        """
        Recursively sets every time_taken_in_seconds value under node to 0.0, in place.

        :param node: A dict, list or scalar taken from a response dict.
        """
        if isinstance(node, dict):
            for key in list(node.keys()):
                if key == TestDirectAgentSessionGoldenParity.VOLATILE_KEY:
                    node[key] = 0.0
                else:
                    TestDirectAgentSessionGoldenParity.zero_volatile(node[key])
        elif isinstance(node, list):
            for item in node:
                TestDirectAgentSessionGoldenParity.zero_volatile(item)

    def check_against_golden(self, golden_name: str, actual: List[Dict[str, Any]]) -> None:
        """
        Compares the normalized stream with the golden file, or rewrites the
        golden file when NEURO_SAN_UPDATE_GOLDEN is exactly "1".

        :param golden_name: File name of the golden JSON under the golden directory.
        :param actual: The normalized stream from the current run.
        """
        golden_path: str = self.GOLDEN_DIR.get_file_in_basis(golden_name)
        if environ.get(self.UPDATE_ENV_VAR) == "1":
            with open(golden_path, "w", encoding="utf-8") as golden_file:
                golden_file.write(dumps(actual, indent=2, sort_keys=True))
                golden_file.write("\n")
            # A regeneration run must never look like a passing comparison.
            self.skipTest(f"golden {golden_name} rewritten; re-run without {self.UPDATE_ENV_VAR}")
        with open(golden_path, "r", encoding="utf-8") as golden_file:
            expected: List[Dict[str, Any]] = loads(golden_file.read())
        self.assertEqual(expected, actual)

    def assert_text_only_wire(self, stream: List[Dict[str, Any]]) -> None:
        """
        Asserts the Phase 1 wire contract on every message: no content-block key
        leaks through, and text, where present, is a plain string. Presence is
        not required here on purpose. BaseMessageDictionaryConverter omits the
        text key for a message whose content is an empty list, so that such a
        message cannot become answer-eligible, and the golden comparison already
        locks exactly which messages carry text (in these goldens, all of them).

        :param stream: The normalized response dicts.
        """
        for response in stream:
            message: Dict[str, Any] = response.get("response")
            self.assertIsInstance(message, dict)
            self.assertNotIn("content", message)
            if "text" in message:
                self.assertIsInstance(message.get("text"), str)

    def test_echo_two_turns_match_golden(self) -> None:
        """
        A plain two-turn echo conversation produces exactly the golden stream,
        including the chat_context carried into and returned from the second turn.
        """
        actual: List[Dict[str, Any]] = self.run_conversation(["hello there", "second turn"])

        self.assert_text_only_wire(actual)
        self.check_against_golden("echo_two_turns_maximal.json", actual)

    def test_anthropic_thinking_marker_answer_matches_golden(self) -> None:
        """
        An answer the mock emits as [thinking, text] blocks reaches the wire as
        the text alone, in exactly the golden stream, so block content never
        changes what a text-only client sees.
        """
        actual: List[Dict[str, Any]] = self.run_conversation(["emit anthropic thinking: the answer"])

        self.assert_text_only_wire(actual)
        self.check_against_golden("echo_anthropic_thinking_marker_maximal.json", actual)

    def test_openai_reasoning_marker_answer_matches_golden(self) -> None:
        """
        An answer the mock emits as an OpenAI Responses reasoning item followed
        by a text item reaches the wire as the text alone, in exactly the golden
        stream, so the OpenAI reasoning shape never changes what a client sees.
        """
        actual: List[Dict[str, Any]] = self.run_conversation(["emit openai reasoning: the answer"])

        self.assert_text_only_wire(actual)
        self.check_against_golden("echo_openai_reasoning_marker_maximal.json", actual)

    def test_gemini_thinking_marker_answer_matches_golden(self) -> None:
        """
        An answer the mock emits as a Gemini thinking block followed by a
        signed text block reaches the wire as the text alone, in exactly the
        golden stream, so the Gemini thinking shape never changes what a client
        sees and the signature in the text block's extras never leaks.
        """
        actual: List[Dict[str, Any]] = self.run_conversation(["emit gemini thinking: the answer"])

        self.assert_text_only_wire(actual)
        self.check_against_golden("echo_gemini_thinking_marker_maximal.json", actual)
