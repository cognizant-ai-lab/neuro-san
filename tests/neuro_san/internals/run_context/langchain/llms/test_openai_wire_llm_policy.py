
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
"""
Unit tests for OpenAiWireLlmPolicy and OpenAiWireLlmFactory, the wiring that
lets an agent network select the SDK-free chat model from its llm_config.
"""

from typing import Any
from typing import Dict
from unittest import IsolatedAsyncioTestCase

from neuro_san.internals.run_context.langchain.llms.openai_wire_llm_factory import OpenAiWireLlmFactory
from neuro_san.internals.run_context.langchain.llms.openai_wire_llm_policy import OpenAiWireLlmPolicy
from neuro_san.internals.run_context.langchain.llms.wire.aiohttp_chat_transport import AiohttpChatTransport
from neuro_san.internals.run_context.langchain.llms.wire.openai_wire_chat_model import OpenAiWireChatModel
from neuro_san.internals.run_context.langchain.llms.wire.pyodide_chat_transport import PyodideChatTransport


class TestOpenAiWireLlmPolicy(IsolatedAsyncioTestCase):
    """
    Tests the policy and factory that make "openai-wire" selectable.
    """

    def test_the_factory_adds_the_class_without_losing_the_stock_ones(self) -> None:
        """
        Registering this factory must extend the stock table, not replace it,
        and must not mutate the parent's default for everyone else.
        """
        factory = OpenAiWireLlmFactory()

        self.assertIn("openai-wire", factory.class_to_llm_policy_type)
        self.assertIn("openai", factory.class_to_llm_policy_type)
        self.assertIn("anthropic", factory.class_to_llm_policy_type)
        self.assertIs(factory.class_to_llm_policy_type["openai-wire"], OpenAiWireLlmPolicy)

    def test_the_factory_takes_no_constructor_arguments(self) -> None:
        """
        Factories named in an llm_info hocon file are instantiated by name with
        nothing to pass them, so everything configurable has to come through
        llm_config instead.
        """
        self.assertIsNotNone(OpenAiWireLlmFactory())

    def test_the_transport_comes_from_the_config(self) -> None:
        """
        Which transport to use is an ordinary llm_config value, so a browser
        deployment selects it the same way it selects anything else.
        """
        policy = OpenAiWireLlmPolicy()
        self.assertIsInstance(policy.create_client({"transport": "aiohttp"}), AiohttpChatTransport)

        other = OpenAiWireLlmPolicy()
        self.assertIsInstance(other.create_client({"transport": "pyodide"}), PyodideChatTransport)

    def test_the_default_transport_is_the_one_that_works_in_a_process(self) -> None:
        """
        An llm_config that says nothing should work in an ordinary process; a
        browser has to ask for the browser transport explicitly.
        """
        policy = OpenAiWireLlmPolicy()
        self.assertIsInstance(policy.create_client({}), AiohttpChatTransport)

    def test_an_unknown_transport_names_the_known_ones(self) -> None:
        """
        A typo in llm_config should say what would have worked.
        """
        policy = OpenAiWireLlmPolicy()

        with self.assertRaises(ValueError) as raised:
            policy.create_client({"transport": "carrier-pigeon"})

        self.assertIn("aiohttp", str(raised.exception))
        self.assertIn("pyodide", str(raised.exception))

    def test_the_model_is_built_from_the_config_and_the_client(self) -> None:
        """
        The chat model gets the transport create_client() made, and reads its
        endpoint and key from the config.
        """
        policy = OpenAiWireLlmPolicy()
        config: Dict[str, Any] = {"base_url": "http://host/v1", "openai_api_key": "secret"}
        client = policy.create_client(config)

        llm = policy.create_llm(config, "a-model", client)

        self.assertIsInstance(llm, OpenAiWireChatModel)
        self.assertIs(llm.transport, client)
        self.assertEqual(llm.base_url, "http://host/v1")
        self.assertEqual(llm.model_name, "a-model")

    async def test_delete_resources_closes_the_transport_once(self) -> None:
        """
        The transport is the only thing this policy holds -- there is no SDK
        client underneath to reach into -- and releasing it twice must be safe.
        """
        policy = OpenAiWireLlmPolicy()
        transport = policy.create_client({"transport": "aiohttp"})

        await policy.delete_resources()
        self.assertIsNone(policy.transport)

        # Second call must not raise.
        await policy.delete_resources()
        self.assertIsNone(transport.session)
