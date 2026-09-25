
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
import inspect
import os

from typing import Any
from typing import Dict
from typing import List
from unittest import TestCase
from unittest.mock import patch

from typing_extensions import override

from langchain_core.messages import HumanMessage
from langchain_openai.chat_models.base import ChatOpenAI
from openai.resources.responses import AsyncResponses

from neuro_san.internals.run_context.langchain.llms.openai_llm_policy import OpenAILlmPolicy


class TestOpenAILlmPolicy(TestCase):
    """
    Test cases for OpenAILlmPolicy.create_llm().

    These tests build the ChatOpenAI exactly the way production does (create_client()
    followed by create_llm()) and then inspect what was built, without ever making
    a network call.
    """

    # Points at a closed local port so that an accidental network call fails fast instead
    # of reaching a real OpenAI endpoint. The key is a dummy; see setUp().
    BASE_CONFIG: Dict[str, Any] = {
        "openai_api_key": "sk-test",
        "openai_api_base": "http://127.0.0.1:9",
        "max_retries": 0,
        "request_timeout": 5,
        "streaming": False,
    }

    @override
    def setUp(self) -> None:
        """
        Pins OPENAI_API_KEY to a dummy value and starts the list of policies that tearDown() releases.

        ChatOpenAI also builds a synchronous client from the OPENAI_API_KEY environment variable,
        so the variable is pinned here to guarantee no real key is ever used.
        """
        env_patcher: Any = patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"})
        env_patcher.start()
        # addCleanup() restores the environment even when tearDown() itself fails part-way through.
        self.addCleanup(env_patcher.stop)
        self.policies: List[OpenAILlmPolicy] = []

    @override
    def tearDown(self) -> None:
        """
        Releases the httpx clients of every OpenAILlmPolicy the test built.
        """
        for policy in self.policies:
            asyncio.run(policy.delete_resources())

    def _build_llm(self, extra_config: Dict[str, Any], model_name: str = "gpt-5.2") -> ChatOpenAI:
        """
        Builds a ChatOpenAI the way production does: create_client() then create_llm().

        :param extra_config: llm_config keys layered on top of BASE_CONFIG
        :param model_name: The OpenAI model name to build the llm for
        :return: The ChatOpenAI instance produced by OpenAILlmPolicy.create_llm()
        """
        config: Dict[str, Any] = dict(self.BASE_CONFIG)
        config.update(extra_config)

        policy: OpenAILlmPolicy = OpenAILlmPolicy()
        # Register before creating anything so tearDown() still runs if create_llm() raises.
        self.policies.append(policy)

        client: Any = policy.create_client(config)
        llm: ChatOpenAI = policy.create_llm(config, model_name, client)
        return llm

    @staticmethod
    def _request_payload(llm: ChatOpenAI) -> Dict[str, Any]:
        """
        Computes the request body langchain-openai would send for a single user message.

        :param llm: The ChatOpenAI instance to inspect
        :return: The keyword arguments that would be passed to the OpenAI SDK create() call
        """
        payload: Dict[str, Any] = llm._get_request_payload([HumanMessage("hi")])
        return payload

    @staticmethod
    def _assert_binds_to_responses_create(payload: Dict[str, Any]) -> None:
        """
        Checks that the payload only uses keyword arguments the Responses API create() accepts.

        Binding against the real SDK signature is what fails with "unexpected keyword argument 'n'"
        when n leaks into a Responses API request, which is the exact symptom of issue #725.

        :param payload: The request payload to check
        :raises TypeError: If the payload carries a keyword argument create() does not accept
        """
        signature: inspect.Signature = inspect.signature(AsyncResponses.create)
        # The leading None stands in for "self" because create is inspected as an unbound method.
        signature.bind(None, **payload)

    def test_default_config_keeps_chat_completions_without_n(self) -> None:
        """
        With use_responses_api absent from llm_config the policy itself does not force an endpoint: the
        llm stays on Chat Completions and no longer sends n. The hocon class default of true is applied
        by DefaultLlmFactory and is not exercised by this policy-level test.
        """
        llm: ChatOpenAI = self._build_llm({})
        payload: Dict[str, Any] = self._request_payload(llm)

        self.assertIsNone(llm.n)
        self.assertNotIn("n", payload)
        # None (not False) is what keeps langchain's auto-routing alive for existing configs.
        self.assertIsNone(llm.use_responses_api)
        self.assertIs(llm._use_responses_api(llm._default_params), False)
        self.assertIn("messages", payload)

    def test_reasoning_dict_auto_routes_to_responses_api_without_n(self) -> None:
        """
        Regression test for issue #725: a "reasoning" dict makes langchain auto-route to the
        Responses API, and the resulting payload must be acceptable to that API (no n).

        create_llm() used to pass n=1 unconditionally. Chat Completions tolerates that, but the
        Responses API has no n parameter, so any config that langchain auto-routed there failed
        client-side. The fix drops n and forwards "use_responses_api" so agents can pick the endpoint.
        """
        llm: ChatOpenAI = self._build_llm({"reasoning": {"effort": "low"}})
        payload: Dict[str, Any] = self._request_payload(llm)

        # The policy forwards use_responses_api from llm_config unchanged, so it must not have pinned
        # Chat Completions. Do not assert None here: langchain-openai 1.6.3 added a model validator
        # that materializes the inferred endpoint on the instance (True once "reasoning" is set),
        # while earlier releases leave the attribute None.
        self.assertIsNot(llm.use_responses_api, False)
        self.assertIs(llm._use_responses_api(llm._default_params), True)
        self.assertNotIn("n", payload)
        self.assertEqual(payload["reasoning"], {"effort": "low"})
        self._assert_binds_to_responses_create(payload)

    def test_use_responses_api_true_is_forwarded(self) -> None:
        """
        An explicit "use_responses_api": true reaches ChatOpenAI and produces a Responses API payload.
        """
        llm: ChatOpenAI = self._build_llm({"use_responses_api": True})
        payload: Dict[str, Any] = self._request_payload(llm)

        self.assertIs(llm.use_responses_api, True)
        self.assertIs(llm._use_responses_api(llm._default_params), True)
        # The Responses API takes "input" where Chat Completions takes "messages".
        self.assertIn("input", payload)
        self.assertNotIn("messages", payload)
        self.assertNotIn("n", payload)
        self._assert_binds_to_responses_create(payload)

    def test_use_responses_api_false_is_forwarded_as_false(self) -> None:
        """
        An explicit "use_responses_api": false reaches ChatOpenAI as False, not as None.
        """
        llm: ChatOpenAI = self._build_llm({"use_responses_api": False})
        payload: Dict[str, Any] = self._request_payload(llm)

        self.assertIs(llm.use_responses_api, False)
        self.assertIs(llm._use_responses_api(llm._default_params), False)
        self.assertIn("messages", payload)

    def test_use_responses_api_false_overrides_auto_routing(self) -> None:
        """
        An explicit false pins Chat Completions even when a "reasoning" dict would otherwise
        auto-route to the Responses API. This is why the key must not go through get_bool():
        an absent key collapsed to False would disable auto-routing for everyone.
        """
        llm: ChatOpenAI = self._build_llm({"use_responses_api": False,
                                           "reasoning": {"effort": "low"}})
        payload: Dict[str, Any] = self._request_payload(llm)

        self.assertIs(llm.use_responses_api, False)
        self.assertIs(llm._use_responses_api(llm._default_params), False)
        self.assertIn("messages", payload)

    def test_reasoning_effort_folds_into_reasoning_on_responses_api(self) -> None:
        """
        On the Responses API path langchain rewrites reasoning_effort into reasoning.effort.
        """
        llm: ChatOpenAI = self._build_llm({"reasoning_effort": "low", "use_responses_api": True})
        payload: Dict[str, Any] = self._request_payload(llm)

        self.assertEqual(payload["reasoning"], {"effort": "low"})
        self.assertNotIn("reasoning_effort", payload)
        self.assertNotIn("n", payload)
        self._assert_binds_to_responses_create(payload)

    def test_create_llm_reads_openai_proxy_from_its_own_env_var(self) -> None:
        """
        Regression test for issue #1308: with no pre-built client, an llm_config that sets
        "openai_organization" but not "openai_proxy" must fall back to OPENAI_PROXY for the
        proxy. Before the fix the proxy was read from the "openai_organization" key, so the
        organization id was handed to ChatOpenAI as the proxy URL and OPENAI_PROXY was ignored.
        """
        config: Dict[str, Any] = dict(self.BASE_CONFIG)
        config["openai_organization"] = "org-from-config"

        policy: OpenAILlmPolicy = OpenAILlmPolicy()
        self.policies.append(policy)

        # OPENAI_PROXY is a closed local port, like openai_api_base, so nothing can reach a real proxy.
        # OPENAI_ORG_ID differs from the config value to show that llm_config wins over the environment.
        env_overrides: Dict[str, str] = {
            "OPENAI_PROXY": "http://127.0.0.1:9",
            "OPENAI_ORG_ID": "org-from-env",
        }
        with patch.dict(os.environ, env_overrides):
            # No client is passed, so create_llm() consults llm_config first and the environment second.
            llm: ChatOpenAI = policy.create_llm(config, "gpt-5.2", None)

        self.assertEqual(llm.openai_organization, "org-from-config")
        self.assertEqual(llm.openai_proxy, "http://127.0.0.1:9")

    def test_create_llm_without_client_reads_each_connection_key(self) -> None:
        """
        Regression test for issue #1308 at the level of the built ChatOpenAI: with no pre-built
        client, each connection setting in llm_config must land on its own ChatOpenAI field.
        Before the fix the organization id was handed to ChatOpenAI as the proxy URL.
        """
        config: Dict[str, Any] = dict(self.BASE_CONFIG)
        config["openai_organization"] = "org-test"
        # A closed local port, like openai_api_base, so nothing can reach a real proxy.
        config["openai_proxy"] = "http://127.0.0.1:9"

        policy: OpenAILlmPolicy = OpenAILlmPolicy()
        self.policies.append(policy)

        # No client is passed, so create_llm() must fall back to the llm_config values themselves.
        llm: ChatOpenAI = policy.create_llm(config, "gpt-5.2", None)

        self.assertEqual(llm.openai_api_key.get_secret_value(), "sk-test")
        self.assertEqual(llm.openai_api_base, "http://127.0.0.1:9")
        self.assertEqual(llm.openai_organization, "org-test")
        self.assertEqual(llm.openai_proxy, "http://127.0.0.1:9")

    def test_store_and_include_from_llm_config_reach_the_payload(self) -> None:
        """
        "store" and "include" from llm_config are forwarded to ChatOpenAI and land in the Responses API
        payload, which still binds against the real create() signature (so no n leaked in either).
        """
        llm: ChatOpenAI = self._build_llm({"use_responses_api": True,
                                           "store": False,
                                           "include": ["reasoning.encrypted_content"]})
        payload: Dict[str, Any] = self._request_payload(llm)

        self.assertIs(llm.store, False)
        self.assertEqual(llm.include, ["reasoning.encrypted_content"])
        self.assertIs(payload["store"], False)
        self.assertEqual(payload["include"], ["reasoning.encrypted_content"])
        self.assertNotIn("n", payload)
        self._assert_binds_to_responses_create(payload)

    def test_store_false_without_include_omits_include(self) -> None:
        """
        "store": false on its own reaches the payload while "include" stays absent, so the policy never
        invents an include list (which Chat Completions would reject and which forces Responses routing).
        """
        llm: ChatOpenAI = self._build_llm({"use_responses_api": True, "store": False})
        payload: Dict[str, Any] = self._request_payload(llm)

        self.assertIs(payload["store"], False)
        self.assertNotIn("include", payload)
        self._assert_binds_to_responses_create(payload)

    def test_store_and_include_absent_are_omitted_from_the_payload(self) -> None:
        """
        With neither "store" nor "include" in llm_config, ChatOpenAI keeps both at None and langchain
        leaves both keys out of the request, so gateways never see fields nobody asked for.
        """
        llm: ChatOpenAI = self._build_llm({"use_responses_api": True})
        payload: Dict[str, Any] = self._request_payload(llm)

        self.assertIsNone(llm.store)
        self.assertIsNone(llm.include)
        self.assertNotIn("store", payload)
        self.assertNotIn("include", payload)
        self._assert_binds_to_responses_create(payload)
