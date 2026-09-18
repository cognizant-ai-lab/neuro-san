
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
# pylint: disable=protected-access

import asyncio
import os

from typing import Any
from typing import Dict
from typing import List
from unittest import TestCase
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import call
from unittest.mock import patch

from typing_extensions import override

from leaf_common.resolution.resolver import Resolver

from neuro_san.internals.run_context.langchain.llms.default_llm_factory import DefaultLlmFactory
from neuro_san.internals.run_context.langchain.llms.gemini_llm_policy import GeminiLlmPolicy


class TestGeminiLlmPolicy(TestCase):
    """
    Test cases for GeminiLlmPolicy.

    Three areas are covered, none of which makes a network call:

    * create_llm(): the chat model is built exactly the way production does (llm_config
      overlaid on the gemini class args by DefaultLlmFactory, then create_llm()) and the
      result is inspected. Constructing the chat model only builds a google-genai client.
    * _disable_afc(): the google-genai SDK logs a misleading "AFC is enabled with max remote
      calls: 10." banner unless Automatic Function Calling is explicitly disabled per request.
      See https://github.com/cognizant-ai-lab/neuro-san/issues/1096
    * delete_resources(): the clients must be reached through the bind() wrapper that
      _disable_afc() returns, as well as on an unwrapped chat model.

    The _disable_afc() and delete_resources() tests use MagicMock stand-ins for the chat model
    so that they do not depend on the Gemini packages being installed. Both Gemini packages are
    optional dependencies, so the tests that need one resolve it lazily through the same
    leaf-common Resolver that LlmPolicy uses and skip themselves when it is absent.
    """

    MODEL_NAME: str = "gemini-3.8-flash"

    # The key is a dummy; see setUp(). max_retries=0 keeps any accidental
    # request from being retried against a real endpoint.
    BASE_CONFIG: Dict[str, Any] = {
        "google_api_key": "test-key",
        "max_retries": 0,
    }

    @override
    def setUp(self) -> None:
        """
        Pins the environment, loads the stock default_llm_info.hocon and starts tracking policies.

        AGENT_LLM_INFO_FILE is removed so that a deployer override present in the environment
        cannot change the class args these tests check. GOOGLE_API_KEY is pinned to a dummy value
        so that a real key can never be picked up from the environment, and OPENAI_API_KEY is
        pinned to a dummy as well so that nothing these tests construct can see a real provider key.
        """
        # Build the replacement environment by hand: patch.dict with clear=False can only
        # override variables, not delete them, so removing AGENT_LLM_INFO_FILE needs a full
        # copy handed to patch.dict with clear=True.
        environment: Dict[str, str] = {}
        for name, value in os.environ.items():
            if name != "AGENT_LLM_INFO_FILE":
                environment[name] = value
        environment["GOOGLE_API_KEY"] = "test-key"
        environment["OPENAI_API_KEY"] = "sk-test"

        env_patcher: Any = patch.dict(os.environ, environment, clear=True)
        env_patcher.start()
        # addCleanup runs even if the rest of setUp or the test itself raises, and stop()
        # restores os.environ exactly as it was before start().
        self.addCleanup(env_patcher.stop)

        # Loaded after the environment is pinned so the stock hocon is what gets read.
        self.factory: DefaultLlmFactory = DefaultLlmFactory()
        self.factory.load()

        # Every GeminiLlmPolicy a test builds goes here so tearDown() can close its clients.
        self.policies: List[GeminiLlmPolicy] = []

        # Resolves the optional Gemini classes lazily, the same way LlmPolicy does, so that a
        # missing package skips the tests that need it instead of failing the module import.
        self.resolver: Resolver = Resolver()

    @override
    def tearDown(self) -> None:
        """
        Closes the google-genai clients of every GeminiLlmPolicy a test built.
        """
        for policy in self.policies:
            asyncio.run(policy.delete_resources())

    def _resolve_chat_model_class(self) -> Any:
        """
        Resolves ChatGoogleGenerativeAI without importing it at module level.

        :return: The ChatGoogleGenerativeAI class, or None when langchain-google-genai is not installed
        """
        # No install_if_missing here: a unit test must never install packages.
        return self.resolver.resolve_class_in_module("ChatGoogleGenerativeAI",
                                                     module_name="langchain_google_genai.chat_models",
                                                     raise_if_not_found=False)

    def _resolve_afc_config_class(self) -> Any:
        """
        Resolves the google-genai SDK's AutomaticFunctionCallingConfig without importing it at module level.

        :return: The AutomaticFunctionCallingConfig class, or None when the google-genai SDK is not installed
        """
        return self.resolver.resolve_class_in_module("AutomaticFunctionCallingConfig",
                                                     module_name="google.genai.types",
                                                     raise_if_not_found=False)

    def _build_llm(self, extra_config: Dict[str, Any]) -> Any:
        """
        Builds the chat model the way production does and unwraps the AFC-disabling bind() wrapper.

        :param extra_config: llm_config keys layered on top of BASE_CONFIG
        :return: The ChatGoogleGenerativeAI instance underneath whatever create_llm() returned
        """
        chat_model_class: Any = self._resolve_chat_model_class()
        if chat_model_class is None:
            self.skipTest("langchain-google-genai not installed")

        llm_config: Dict[str, Any] = dict(self.BASE_CONFIG)
        llm_config["model_name"] = self.MODEL_NAME
        llm_config.update(extra_config)

        # Go through the factory rather than handing create_llm() a bare llm_config: production
        # always does, and ChatGoogleGenerativeAI rejects a bare config (its "n" field is a
        # non-optional int that the gemini class args supply). This also guards that every
        # declared gemini class arg is something the chat model will actually accept.
        config: Dict[str, Any] = self.factory.create_full_llm_config(llm_config, {})

        policy: GeminiLlmPolicy = GeminiLlmPolicy()
        # Register before creating anything so tearDown() still runs if create_llm() raises.
        self.policies.append(policy)

        result: Any = policy.create_llm(config, config["model_name"], None)
        # delete_resources() reaches the clients through policy.llm, so hand it what was built.
        policy.llm = result

        # create_llm() returns _disable_afc(llm), which on a current langchain-core is a
        # RunnableBinding whose "bound" attribute is the real chat model.
        llm: Any = getattr(result, "bound", result)
        self.assertIsInstance(llm, chat_model_class)
        return llm

    @staticmethod
    def _make_chat_model_stub(bind_tools_aware: bool) -> MagicMock:
        """
        Builds a stand-in for ChatGoogleGenerativeAI for the _disable_afc() and delete_resources() tests.

        The stub's bind() records its keyword arguments and returns a binding whose "bound"
        attribute points back at the stub, mirroring langchain-core's RunnableBinding. Both
        mocks carry an explicit spec so that hasattr() answers honestly: the stub has no
        "bound" attribute (delete_resources() must treat it as an unwrapped model) and the
        binding only has bind_tools() when the test asks for a chat-model-aware one.

        :param bind_tools_aware: True to give the binding a bind_tools() method, as langchain-core
                                 >= 1.4 does; False for the older generic RunnableBinding without one
        :return: The stub chat model
        """
        llm: MagicMock = MagicMock(spec=["bind", "client", "async_client"])
        binding_spec: List[str] = ["bound", "kwargs"]
        if bind_tools_aware:
            binding_spec.append("bind_tools")
        binding: MagicMock = MagicMock(spec=binding_spec)
        binding.bound = llm
        llm.bind.return_value = binding

        # delete_resources() calls client.close() synchronously and awaits async_client.aclose().
        llm.client = MagicMock(spec=["close"])
        llm.async_client = MagicMock(spec=["aclose"])
        llm.async_client.aclose = AsyncMock()
        return llm

    @staticmethod
    def _attach_close_recorder(llm: MagicMock) -> MagicMock:
        """
        Attaches one recorder to both client close methods of a stub so their call order can be checked.

        :param llm: The stub chat model built by _make_chat_model_stub()
        :return: A mock whose mock_calls lists close() and aclose() in the order they happened
        """
        recorder: MagicMock = MagicMock()
        recorder.attach_mock(llm.client.close, "close")
        recorder.attach_mock(llm.async_client.aclose, "aclose")
        return recorder

    def test_include_thoughts_and_thinking_level_are_forwarded(self) -> None:
        """
        "include_thoughts": true and "thinking_level": "low" in llm_config both land on the chat model.
        """
        llm: Any = self._build_llm({"include_thoughts": True, "thinking_level": "low"})

        self.assertIs(llm.include_thoughts, True)
        self.assertEqual(llm.thinking_level, "low")

    def test_include_thoughts_absent_stays_none(self) -> None:
        """
        Without "include_thoughts" in llm_config the chat model keeps langchain's None default,
        so the field is left out of the request rather than sent as an explicit false.
        """
        llm: Any = self._build_llm({})

        self.assertIsNone(llm.include_thoughts)

    def test_factory_declares_include_thoughts_default(self) -> None:
        """
        The gemini class args in default_llm_info.hocon declare include_thoughts with a null
        default, so a fully specified config carries the key as None unless llm_config sets it.
        """
        full_config: Dict[str, Any] = self.factory.create_full_llm_config({"model_name": self.MODEL_NAME}, {})

        self.assertEqual(full_config["class"], "gemini")
        self.assertIn("include_thoughts", full_config)
        self.assertIsNone(full_config["include_thoughts"])

    def test_factory_forwards_include_thoughts_true(self) -> None:
        """
        "include_thoughts": true in llm_config survives the overlay onto the gemini class defaults.
        """
        full_config: Dict[str, Any] = self.factory.create_full_llm_config(
            {"model_name": self.MODEL_NAME, "include_thoughts": True}, {})

        self.assertEqual(full_config["class"], "gemini")
        self.assertIs(full_config["include_thoughts"], True)

    def test_disable_afc_binds_afc_disable(self) -> None:
        """
        On a chat-model-aware langchain-core, the llm is bound with the AFC-disable setting.
        """
        afc_config_class: Any = self._resolve_afc_config_class()
        if afc_config_class is None:
            self.skipTest("google-genai SDK not installed")
        llm: MagicMock = self._make_chat_model_stub(bind_tools_aware=True)

        result: Any = GeminiLlmPolicy()._disable_afc(llm)

        self.assertIs(result, llm.bind.return_value)
        self.assertIs(result.bound, llm)
        afc: Any = llm.bind.call_args.kwargs.get("automatic_function_calling")
        self.assertIsInstance(afc, afc_config_class)
        self.assertIs(afc.disable, True)

    def test_disable_afc_passthrough_on_legacy_langchain_core(self) -> None:
        """
        When bind() yields a binding without bind_tools(), the raw llm is returned unchanged.
        """
        if self._resolve_afc_config_class() is None:
            self.skipTest("google-genai SDK not installed")
        llm: MagicMock = self._make_chat_model_stub(bind_tools_aware=False)

        result: Any = GeminiLlmPolicy()._disable_afc(llm)

        self.assertIs(result, llm)

    def test_disable_afc_passthrough_without_google_genai(self) -> None:
        """
        Without the google-genai SDK there is no AFC, so the llm is returned unchanged.
        """
        if self._resolve_afc_config_class() is not None:
            self.skipTest("google-genai SDK is installed")
        llm: MagicMock = self._make_chat_model_stub(bind_tools_aware=True)

        result: Any = GeminiLlmPolicy()._disable_afc(llm)

        self.assertIs(result, llm)
        llm.bind.assert_not_called()

    def test_delete_resources_unwraps_binding(self) -> None:
        """
        delete_resources() must reach the clients through a bind() wrapper.
        """
        llm: MagicMock = self._make_chat_model_stub(bind_tools_aware=True)
        recorder: MagicMock = self._attach_close_recorder(llm)
        policy: GeminiLlmPolicy = GeminiLlmPolicy()
        policy.llm = llm.bind(automatic_function_calling="anything")

        asyncio.run(policy.delete_resources())

        self.assertEqual(recorder.mock_calls, [call.close(), call.aclose()])
        self.assertIsNone(policy.llm)

    def test_delete_resources_works_unwrapped(self) -> None:
        """
        delete_resources() must still work when the llm is not wrapped.
        """
        llm: MagicMock = self._make_chat_model_stub(bind_tools_aware=True)
        recorder: MagicMock = self._attach_close_recorder(llm)
        policy: GeminiLlmPolicy = GeminiLlmPolicy()
        policy.llm = llm

        asyncio.run(policy.delete_resources())

        self.assertEqual(recorder.mock_calls, [call.close(), call.aclose()])
        self.assertIsNone(policy.llm)
