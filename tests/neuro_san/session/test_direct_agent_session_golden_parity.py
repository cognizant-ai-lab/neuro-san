
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
from neuro_san.message.content_blocks.langchain_v1_content_blocks_format import LangchainV1ContentBlocksFormat
from neuro_san.message.processors.basic_message_processor import BasicMessageProcessor
from neuro_san.message.types.chat_message_type import ChatMessageType
from neuro_san.message.utils.content_utils import ContentUtils
from neuro_san.session.direct_agent_session import DirectAgentSession
from neuro_san.session.external_agent_session_factory import ExternalAgentSessionFactory
from neuro_san.session.session_invocation_context import SessionInvocationContext


class TestDirectAgentSessionGoldenParity(TestCase):
    """
    Golden-parity test for the client-visible wire stream of a whole request.

    The message pipeline carries LangChain content blocks while the dicts a
    client receives for text traffic keep their shape, and the content_blocks
    wrapper is added only to messages whose content says more than its text.
    This test locks both end to end: it drives the chat_mock_llm_echo network
    through DirectAgentSession.streaming_chat with the MAXIMAL filter, so
    nothing is filtered out, and compares the complete stream of response
    dicts with a golden file under golden/.

    The network is a single front man with no tools, so the streams hold the
    SYSTEM (first turn only), HUMAN, AI, AGENT token accounting and
    AGENT_FRAMEWORK messages. Tool results, sub-agent origins, error frames and
    sly_data would need a tool-calling mock network.

    Five conversations are locked: a two-turn echo, which carries chat_context
    into the second turn; the same two turns with the client sending the
    turn-1 AI entry back inside chat_context as content blocks, which locks
    what the server restores from them and returns in the turn-2
    chat_context; and one turn for each provider marker of the mock
    (Anthropic thinking, OpenAI reasoning, Gemini thinking), whose block
    content reaches the wire as the text plus the content_blocks wrapper while
    every other message in the stream stays as it was.

    time_taken_in_seconds values are zeroed before comparing, and the empty
    keep-alive dicts are dropped. Each conversation also checks that no
    executor thread outlives the session.

    To regenerate the goldens after an intended wire change, run the test with
    NEURO_SAN_TEST_UPDATE_GOLDEN=1. The files are rewritten and the tests
    report skipped, so a regeneration run can never pass by comparing a file
    with itself.
    """

    # Registry hocon of the mock network under test. It has no tools and no
    # external agents, so no provider key or network access is needed.
    AGENT_HOCON: str = "chat_mock_llm_echo.hocon"

    # Locates the golden files relative to this module.
    GOLDEN_DIR: FileOfClass = FileOfClass(__file__, path_to_basis="golden")

    # The one key whose value depends on wall-clock time.
    VOLATILE_KEY: str = "time_taken_in_seconds"

    # Set this environment variable to rewrite the golden files from the current run.
    UPDATE_ENV_VAR: str = "NEURO_SAN_TEST_UPDATE_GOLDEN"

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

    def run_conversation(self, turns: List[str],
                         client_blocks: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """
        Sends the turns through one session as a single conversation and
        collects every response dict the client would receive.

        :param turns: The user inputs, in order.
        :param client_blocks: Content blocks the client sends back on the
                turn-1 AI entry of the chat_context it carries into turn 2,
                as a block-aware client would. None sends the chat_context
                back as received.
        :return: The normalized stream of response dicts across all turns.
        """
        threads_before: int = active_count()
        session: DirectAgentSession = self.create_session()
        stream: List[Dict[str, Any]] = []
        chat_context: Optional[Dict[str, Any]] = None
        try:
            # Send each turn with the chat_context the previous turn returned.
            index: int = None
            turn: str = None
            for index, turn in enumerate(turns):
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
                # Record every frame of the turn and feed it to the processor.
                response: Dict[str, Any] = None
                for response in session.streaming_chat(request):
                    if not response:
                        # Keep-alive frame from the sync generator; timing dependent, no content.
                        continue
                    stream.append(response)
                    message: Dict[str, Any] = response.get("response")
                    processor.process_message(message, message.get("type"))
                chat_context = processor.get_chat_context()
                if index == 0 and client_blocks is not None:
                    chat_context = self.send_blocks_back(chat_context, client_blocks)
        finally:
            session.close()
        # A thread still alive here belongs to a turn whose executor was never returned.
        self.assertLessEqual(self.wait_for_thread_count(threads_before), threads_before,
                             "a turn's executor thread outlived the session")
        return self.normalize(stream)

    def send_blocks_back(self, chat_context: Dict[str, Any],
                         client_blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Rewrites the one AI entry of a chat_context the way a block-aware
        client sends it back: the blocks become its content_blocks wrapper
        and their flattened text becomes its text.

        :param chat_context: The chat_context a turn returned.
        :param client_blocks: The content blocks the client sends back for the AI entry.
        :return: A deep copy of chat_context with its AI entry rewritten.
        """
        # The processor hands back the very dict that sits in the recorded
        # stream, so the copy keeps the recorded frame as the server sent it.
        rewritten: Dict[str, Any] = deepcopy(chat_context)
        histories: List[Dict[str, Any]] = rewritten.get("chat_histories", [])
        self.assertEqual(len(histories), 1)
        ai_entries: List[Dict[str, Any]] = []
        # Collect the AI entries of the front man's history.
        entry: Dict[str, Any] = None
        for entry in histories[0].get("messages", []):
            if entry.get("type") == ChatMessageType.AI:
                ai_entries.append(entry)
        self.assertEqual(len(ai_entries), 1, "expected exactly one AI entry to send blocks back on")
        ai_entry: Dict[str, Any] = ai_entries[0]
        ai_entry["content_blocks"] = ContentUtils.wrap_content_blocks(client_blocks)
        ai_entry["text"] = ContentUtils.flatten_to_text(client_blocks)
        return rewritten

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
        golden file when NEURO_SAN_TEST_UPDATE_GOLDEN is exactly "1".

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

    def assert_wire_contract(self, stream: List[Dict[str, Any]]) -> None:
        """
        Asserts the wire contract on every message: no raw content key leaks
        through, text, where present, is a plain string, and content_blocks,
        where present, is the langchain_v1 wrapper whose blocks flatten to that
        text. Text presence is not required here on purpose: the converter
        omits text for empty-list content, and the golden comparison locks
        exactly which messages carry which keys. The history entries inside
        chat_context follow the same content_blocks rule: the server's own
        history is text-only, and an entry carries content_blocks only when
        the client sent blocks back and the server restored them.

        :param stream: The normalized response dicts.
        """
        # Check every frame of the stream, history entries included.
        response: Dict[str, Any] = None
        for response in stream:
            message: Dict[str, Any] = response.get("response")
            self.assertIsInstance(message, dict)
            self.assertNotIn("content", message)
            if "text" in message:
                self.assertIsInstance(message.get("text"), str)
            if "content_blocks" in message:
                self.assert_blocks_match_text(message)
            # Check each history the frame carries in its chat_context.
            history: Dict[str, Any] = None
            for history in message.get("chat_context", {}).get("chat_histories", []):
                # Check each entry of that history.
                history_message: Dict[str, Any] = None
                for history_message in history.get("messages", []):
                    if "content_blocks" in history_message:
                        self.assert_blocks_match_text(history_message)

    def assert_blocks_match_text(self, message: Dict[str, Any]) -> None:
        """
        Asserts that a message's content_blocks is the langchain_v1 wrapper
        around a non-empty block list that flattens to the message's text.

        :param message: A ChatMessage dict that carries content_blocks.
        """
        wrapper: Dict[str, Any] = message.get("content_blocks")
        self.assertEqual(wrapper.get("format"), LangchainV1ContentBlocksFormat.NAME)
        self.assertIsInstance(wrapper.get("blocks"), list)
        self.assertGreater(len(wrapper.get("blocks")), 0)
        self.assertEqual(ContentUtils.flatten_to_text(wrapper.get("blocks")), message.get("text"))

    def test_echo_two_turns_match_golden(self) -> None:
        """
        A plain two-turn echo conversation produces exactly the golden stream,
        including the chat_context carried into and returned from the second turn.
        """
        actual: List[Dict[str, Any]] = self.run_conversation(["hello there", "second turn"])

        self.assert_wire_contract(actual)
        self.check_against_golden("echo_two_turns_maximal.json", actual)

    def test_echo_two_turns_with_client_blocks_match_golden(self) -> None:
        """
        The two-turn echo with the client sending the turn-1 AI entry back as
        a reasoning block plus a phased text block produces exactly the golden
        stream. This locks what the server restores from client-supplied
        blocks: the AI entry comes back in the turn-2 chat_context with the
        phased text block kept and the reasoning block gone, because a
        message bound for a model's chat history loses its reasoning until
        the wire names the provider that produced it. Its text stays equal
        to the flattened blocks the client sent.
        """
        client_blocks: List[Dict[str, Any]] = [
            {
                "type": "reasoning",
                "reasoning": "The user greets me, so I greet back.",
            },
            {
                "type": "text",
                "text": "hello there",
                "phase": "final_answer",
            },
        ]
        actual: List[Dict[str, Any]] = self.run_conversation(
            ["hello there", "second turn"], client_blocks=client_blocks)

        self.assert_wire_contract(actual)
        self.check_against_golden("echo_two_turns_client_blocks_maximal.json", actual)

    def test_anthropic_thinking_marker_answer_matches_golden(self) -> None:
        """
        An answer the mock emits as [thinking, text] blocks reaches the wire as
        the text plus a content_blocks wrapper carrying the reasoning block, in
        exactly the golden stream; every other message is unchanged.
        """
        actual: List[Dict[str, Any]] = self.run_conversation(["emit anthropic thinking: the answer"])

        self.assert_wire_contract(actual)
        self.check_against_golden("echo_anthropic_thinking_marker_maximal.json", actual)

    def test_openai_reasoning_marker_answer_matches_golden(self) -> None:
        """
        An answer the mock emits as an OpenAI Responses reasoning item followed
        by a text item reaches the wire as the text plus a content_blocks
        wrapper with one reasoning block per summary part, in exactly the golden
        stream; every other message is unchanged.
        """
        actual: List[Dict[str, Any]] = self.run_conversation(["emit openai reasoning: the answer"])

        self.assert_wire_contract(actual)
        self.check_against_golden("echo_openai_reasoning_marker_maximal.json", actual)

    def test_gemini_thinking_marker_answer_matches_golden(self) -> None:
        """
        An answer the mock emits as a Gemini thinking block followed by a
        signed text block reaches the wire as the text plus a content_blocks
        wrapper, thought signature included in the text block's extras, in
        exactly the golden stream; every other message is unchanged.
        """
        actual: List[Dict[str, Any]] = self.run_conversation(["emit gemini thinking: the answer"])

        self.assert_wire_contract(actual)
        self.check_against_golden("echo_gemini_thinking_marker_maximal.json", actual)
