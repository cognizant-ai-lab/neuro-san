
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
# One TestCase per source class is the convention here, and this policy has a lot of observable behaviour.
# pylint: disable=too-many-public-methods

import asyncio
import inspect
import json
import os

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from types import ModuleType
from unittest import TestCase
from unittest.mock import patch

from typing_extensions import override

from langchain_core.load.dump import dumpd
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_openai.chat_models.base import ChatOpenAI
from openai import DEFAULT_MAX_RETRIES
from openai import OpenAIError
from openai.resources.responses import AsyncResponses

from neuro_san.internals.run_context.langchain.llms.azure_llm_policy import AzureLlmPolicy
from neuro_san.internals.run_context.langchain.llms.default_llm_factory import DefaultLlmFactory
from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler import LlmTokenCallbackHandler
from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler import PRICE_MODEL_METADATA_KEY
from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler import PROVIDER_METADATA_KEY
from neuro_san.internals.run_context.langchain.util.openai_httpx import OpenAIHttpx
from neuro_san.internals.run_context.langchain.util.api_key_error_check import ApiKeyErrorCheck

from tests.neuro_san.internals.run_context.langchain.token_counting.owning_agent_scope import owning_agent_scope


class TestAzureLlmPolicy(TestCase):
    """
    Test cases for AzureLlmPolicy.

    The tests build the chat model exactly the way production does (create_client() followed by
    create_llm()) and inspect what was built. The wire-level tests swap the policy's httpx client
    for one with a MockTransport, so a request is really sent through the OpenAI SDK and
    captured, without any network access. The transport comes from the httpx library behind
    the installed SDK (httpx or httpx2), as the SDK requires.
    """

    HTTPX: ModuleType = OpenAIHttpx.module()

    ENDPOINT: str = "https://unit-test.openai.azure.com"
    V1_BASE_URL: str = ENDPOINT + "/openai/v1/"
    # The OpenAI snapshot behind a deployment, the shape the azure-* entries in default_llm_info.hocon
    # resolve model_name to.
    MODEL_NAME: str = "gpt-4o-2024-08-06"
    DEPLOYMENT_NAME: str = "gpt-4o"
    API_KEY: str = "azure-test-key"

    # Environment variables the policy or langchain-openai read; cleared in setUp() so every test
    # controls them fully.
    ENV_KEYS: Tuple[str, ...] = ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT_NAME",
                                 "AZURE_OPENAI_AD_TOKEN", "OPENAI_API_KEY", "OPENAI_API_BASE", "OPENAI_ORG_ID",
                                 "OPENAI_PROXY", "OPENAI_API_VERSION")

    BASE_CONFIG: Dict[str, Any] = {
        "azure_endpoint": ENDPOINT,
        "openai_api_key": API_KEY,
        "deployment_name": DEPLOYMENT_NAME,
        "max_retries": 0,
        "request_timeout": 5,
        "streaming": False,
    }

    # Minimal successful bodies for the two endpoints Azure's v1 API serves. Chat Completions names the
    # OpenAI snapshot as the response model; the Responses API names the deployment (both seen live).
    CHAT_RESPONSE: Dict[str, Any] = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": MODEL_NAME,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    RESPONSES_RESPONSE: Dict[str, Any] = {
        "id": "resp_test",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": DEPLOYMENT_NAME,
        "output": [{"type": "message", "id": "msg_test", "status": "completed", "role": "assistant",
                    "content": [{"type": "output_text", "text": "hello", "annotations": []}]}],
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2,
                  "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}},
    }

    @override
    def setUp(self) -> None:
        """
        Clears every environment variable the policy reads, resets the one-time warning flag, and
        starts the lists that tearDown() releases.
        """
        env_patcher: Any = patch.dict(os.environ)
        env_patcher.start()
        # addCleanup() restores the environment (including deletions) even when tearDown() fails part-way.
        self.addCleanup(env_patcher.stop)
        for key in self.ENV_KEYS:
            os.environ.pop(key, None)

        # The warning about legacy keys fires once per process; each test starts from a clean slate.
        AzureLlmPolicy.legacy_keys_warned = False
        self.addCleanup(setattr, AzureLlmPolicy, "legacy_keys_warned", False)

        self.policies: List[AzureLlmPolicy] = []
        self.requests: List[Any] = []

    @override
    def tearDown(self) -> None:
        """
        Releases the httpx clients of every AzureLlmPolicy the test built.
        """
        for policy in self.policies:
            asyncio.run(policy.delete_resources())

    def _make_config(self, extra_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Layers test-specific keys over BASE_CONFIG. A value of None removes the key, so tests can
        exercise the environment fallbacks.

        :param extra_config: Keys to add to or remove from BASE_CONFIG
        :return: The llm_config to hand to the policy
        """
        config: Dict[str, Any] = dict(self.BASE_CONFIG)
        for key, value in extra_config.items():
            if value is None:
                config.pop(key, None)
            else:
                config[key] = value
        return config

    def _build_policy(self, extra_config: Dict[str, Any], model_name: Optional[str] = MODEL_NAME,
                      capture: bool = False) -> Tuple[AzureLlmPolicy, ChatOpenAI]:
        """
        Builds the chat model the way production does: create_client() then create_llm().

        :param extra_config: llm_config keys layered on top of BASE_CONFIG (None removes a key)
        :param model_name: The model name handed to create_llm(), as the llm_info resolution would
        :param capture: When True the policy's httpx client is replaced by one whose MockTransport
                        records every request in self.requests and answers with a canned body
        :return: A tuple of (policy, chat model)
        """
        config: Dict[str, Any] = self._make_config(extra_config)

        policy: AzureLlmPolicy = AzureLlmPolicy()
        # Register before creating anything so tearDown() still runs if create_llm() raises.
        self.policies.append(policy)

        client: Any = None
        if capture:
            # autospec makes the mock accept the bound "self", which the side effect receives as policy.
            with patch.object(AzureLlmPolicy, "create_http_client", autospec=True,
                              side_effect=self._install_mock_http_client):
                client = policy.create_client(config)
        else:
            client = policy.create_client(config)

        llm: ChatOpenAI = policy.create_llm(config, model_name, client)
        return policy, llm

    def _install_mock_http_client(self, policy: AzureLlmPolicy, config: Dict[str, Any]) -> None:
        """
        Stand-in for OpenAILlmPolicy.create_http_client(): gives the policy an httpx client that
        never touches the network.

        :param policy: The policy being built
        :param config: The fully specified llm config (unused, the signature must match)
        """
        _ = config
        policy.http_client = self.HTTPX.AsyncClient(transport=self.HTTPX.MockTransport(self._handle_request))

    def _handle_request(self, request: Any) -> Any:
        """
        MockTransport handler: records the request and answers like Azure's v1 API would.

        :param request: The Request the OpenAI SDK built, of the httpx library behind the SDK
        :return: A Response of that library with a canned Chat Completions or Responses API body,
                chosen by the request path
        """
        self.requests.append(request)
        body: Dict[str, Any] = self.CHAT_RESPONSE
        if request.url.path.endswith("/responses"):
            # Azure's Responses API echoes whatever deployment it was asked for as the response model.
            body = dict(self.RESPONSES_RESPONSE)
            body["model"] = json.loads(request.content).get("model")
        return self.HTTPX.Response(200, json=body, request=request)

    @staticmethod
    def _request_payload(llm: ChatOpenAI) -> Dict[str, Any]:
        """
        Computes the request body langchain-openai would send for a single user message.

        :param llm: The chat model to inspect
        :return: The keyword arguments that would be passed to the OpenAI SDK create() call
        """
        payload: Dict[str, Any] = llm._get_request_payload([HumanMessage("hi")])
        return payload

    @staticmethod
    def _assert_binds_to_responses_create(payload: Dict[str, Any]) -> None:
        """
        Checks that the payload only uses keyword arguments the Responses API create() accepts.

        :param payload: The request payload to check
        :raises TypeError: If the payload carries a keyword argument create() does not accept
        """
        signature: inspect.Signature = inspect.signature(AsyncResponses.create)
        # The leading None stands in for "self" because create is inspected as an unbound method.
        signature.bind(None, **payload)

    @staticmethod
    def _sent_body(request: Any) -> Dict[str, Any]:
        """
        Decodes the JSON body of a captured request.

        :param request: A Request recorded by _handle_request()
        :return: The decoded body
        """
        body: Dict[str, Any] = json.loads(request.content)
        return body

    # ---- Where requests go -------------------------------------------------------------------

    def test_base_url_is_the_v1_api_under_the_endpoint(self) -> None:
        """
        The SDK client and the chat model both point at {endpoint}/openai/v1/.
        """
        policy, llm = self._build_policy({})

        self.assertEqual(str(policy.async_openai_client.base_url), self.V1_BASE_URL)
        self.assertEqual(llm.openai_api_base, self.V1_BASE_URL)

    def test_endpoint_falls_back_to_the_environment(self) -> None:
        """
        Without azure_endpoint in llm_config the AZURE_OPENAI_ENDPOINT environment variable is used.
        """
        with patch.dict(os.environ, {"AZURE_OPENAI_ENDPOINT": "https://from-env.openai.azure.com/"}):
            policy, _ = self._build_policy({"azure_endpoint": None})

        self.assertEqual(str(policy.async_openai_client.base_url), "https://from-env.openai.azure.com/openai/v1/")

    def test_endpoint_that_already_carries_the_v1_path_is_not_doubled(self) -> None:
        """
        An endpoint pasted from Azure's quickstarts already ends in /openai/v1; the path is kept as is.
        """
        policy, _ = self._build_policy({"azure_endpoint": self.ENDPOINT + "/openai/v1/"})

        self.assertEqual(str(policy.async_openai_client.base_url), self.V1_BASE_URL)

    def test_empty_endpoint_counts_as_missing(self) -> None:
        """
        The Dockerfiles export AZURE_OPENAI_ENDPOINT="", which must read as "not configured" and produce
        an error that names the variable, so the friendly API-key hint still matches it.
        """
        with patch.dict(os.environ, {"AZURE_OPENAI_ENDPOINT": ""}):
            with self.assertRaises(OpenAIError) as context:
                self._build_policy({"azure_endpoint": None})

        self.assertIn("AZURE_OPENAI_ENDPOINT", str(context.exception))
        # Nothing to leak: the configuration is checked before the httpx client is opened.
        self.assertIsNone(getattr(self.policies[-1], "http_client", None))
        hint: str = ApiKeyErrorCheck.check_for_api_key_exception(context.exception)
        self.assertIn("AZURE_OPENAI_ENDPOINT", hint)

    def test_whitespace_only_endpoint_counts_as_missing(self) -> None:
        """
        A whitespace-only endpoint, in llm_config or the environment, is "not configured" too. Left alone
        it would strip down to the relative URL /openai/v1/.
        """
        with self.assertRaises(OpenAIError) as configured:
            self._build_policy({"azure_endpoint": "   "})
        self.assertIn("AZURE_OPENAI_ENDPOINT", str(configured.exception))

        with patch.dict(os.environ, {"AZURE_OPENAI_ENDPOINT": " \t"}):
            with self.assertRaises(OpenAIError) as from_env:
                self._build_policy({"azure_endpoint": None})
        self.assertIn("AZURE_OPENAI_ENDPOINT", str(from_env.exception))
        # Nothing to leak: the configuration is checked before the httpx client is opened.
        self.assertIsNone(getattr(self.policies[-1], "http_client", None))

    def test_openai_api_base_from_llm_config_is_used_verbatim_without_an_endpoint(self) -> None:
        """
        A gateway in front of Azure is reached by giving its full base URL as openai_api_base.
        """
        gateway: str = "http://127.0.0.1:9/gateway/v1/"
        policy, llm = self._build_policy({"azure_endpoint": None, "openai_api_base": gateway})

        self.assertEqual(str(policy.async_openai_client.base_url), gateway)
        self.assertEqual(llm.openai_api_base, gateway)

    def test_openai_api_base_in_llm_config_wins_over_the_endpoint_environment_variable(self) -> None:
        """
        A per-agent gateway URL in llm_config beats a server-wide AZURE_OPENAI_ENDPOINT, the same way llm_config
        wins over the environment for the credential and the deployment name.
        """
        gateway: str = "http://127.0.0.1:9/gateway/v1/"
        with patch.dict(os.environ, {"AZURE_OPENAI_ENDPOINT": "https://shared.openai.azure.com"}):
            policy, _ = self._build_policy({"azure_endpoint": None, "openai_api_base": gateway})

        self.assertEqual(str(policy.async_openai_client.base_url), gateway)

    def test_endpoint_whitespace_is_stripped(self) -> None:
        """
        Surrounding whitespace, as a copy-pasted environment value may carry, does not end up in the URL.
        """
        policy, _ = self._build_policy({"azure_endpoint": "  " + self.ENDPOINT + "/ "})

        self.assertEqual(str(policy.async_openai_client.base_url), self.V1_BASE_URL)

    def test_openai_api_base_environment_variable_is_not_consulted(self) -> None:
        """
        OPENAI_API_BASE belongs to the "openai" class; an Azure agent without an endpoint fails clearly
        instead of being redirected to whatever gateway that variable names.
        """
        with patch.dict(os.environ, {"OPENAI_API_BASE": "http://127.0.0.1:9/gateway/v1/"}):
            with self.assertRaises(OpenAIError) as context:
                self._build_policy({"azure_endpoint": None})

        self.assertIn("AZURE_OPENAI_ENDPOINT", str(context.exception))

    # ---- The credential ------------------------------------------------------------------------

    def test_api_key_from_llm_config_wins_over_the_environment(self) -> None:
        """
        openai_api_key in llm_config is used even when AZURE_OPENAI_API_KEY is set.
        """
        with patch.dict(os.environ, {"AZURE_OPENAI_API_KEY": "from-env"}):
            policy, llm = self._build_policy({})

        self.assertEqual(policy.async_openai_client.api_key, self.API_KEY)
        self.assertEqual(llm.openai_api_key.get_secret_value(), self.API_KEY)

    def test_azure_key_environment_variable_wins_over_openai_key(self) -> None:
        """
        Without a key in llm_config, AZURE_OPENAI_API_KEY is preferred over OPENAI_API_KEY.
        """
        with patch.dict(os.environ, {"AZURE_OPENAI_API_KEY": "azure-env-key", "OPENAI_API_KEY": "openai-env-key"}):
            policy, _ = self._build_policy({"openai_api_key": None})

        self.assertEqual(policy.async_openai_client.api_key, "azure-env-key")

    def test_openai_key_is_the_last_fallback(self) -> None:
        """
        OPENAI_API_KEY alone is enough: it is the last fallback after openai_api_key and AZURE_OPENAI_API_KEY.
        """
        with patch.dict(os.environ, {"OPENAI_API_KEY": "openai-env-key"}):
            policy, _ = self._build_policy({"openai_api_key": None})

        self.assertEqual(policy.async_openai_client.api_key, "openai-env-key")

    def test_entra_token_wins_over_the_api_key(self) -> None:
        """
        A configured azure_ad_token is what the SDK sends as the Bearer token, even when a key is set too.
        """
        policy, _ = self._build_policy({"azure_ad_token": "entra-token"})

        self.assertEqual(policy.async_openai_client.api_key, "entra-token")

    def test_missing_credential_raises_naming_the_environment_variables(self) -> None:
        """
        With no key or token anywhere the policy fails before any request, and the friendly API-key
        hint recognises the error.
        """
        with self.assertRaises(OpenAIError) as context:
            self._build_policy({"openai_api_key": None})

        self.assertIn("AZURE_OPENAI_API_KEY", str(context.exception))
        self.assertIsNone(getattr(self.policies[-1], "http_client", None))
        hint: str = ApiKeyErrorCheck.check_for_api_key_exception(context.exception)
        self.assertIn("AZURE_OPENAI_API_KEY", hint)

    # ---- The deployment name -------------------------------------------------------------------

    def test_deployment_name_is_the_wire_model_on_both_endpoints(self) -> None:
        """
        Azure routes by deployment, so the chat model's model, and "model" in the request, is deployment_name,
        not the OpenAI snapshot the llm_info entry resolved to, on the Responses API and on Chat Completions alike.
        """
        _, responses_llm = self._build_policy({"use_responses_api": True})
        _, chat_llm = self._build_policy({"use_responses_api": False})

        self.assertEqual(responses_llm.model_name, self.DEPLOYMENT_NAME)
        self.assertEqual(self._request_payload(responses_llm).get("model"), self.DEPLOYMENT_NAME)
        self.assertEqual(self._request_payload(chat_llm).get("model"), self.DEPLOYMENT_NAME)

    def test_deployment_name_falls_back_to_the_environment(self) -> None:
        """
        Without deployment_name in llm_config the AZURE_OPENAI_DEPLOYMENT_NAME environment variable is used.
        """
        with patch.dict(os.environ, {"AZURE_OPENAI_DEPLOYMENT_NAME": "env-deployment"}):
            _, llm = self._build_policy({"deployment_name": None})

        self.assertEqual(llm.model_name, "env-deployment")
        self.assertEqual(self._request_payload(llm).get("model"), "env-deployment")

    def test_model_name_is_the_last_resort_deployment_name(self) -> None:
        """
        With neither deployment_name nor the environment variable, the resolved model id is sent, which
        serves llm_configs whose model_name is a deployment name llm_info does not know (and so leaves as is).
        """
        # In production the model name create_llm() receives comes from the config, so give both.
        _, llm = self._build_policy({"deployment_name": None, "model_name": "my-deployment"},
                                    model_name="my-deployment")

        self.assertEqual(llm.model_name, "my-deployment")
        self.assertEqual(self._request_payload(llm).get("model"), "my-deployment")
        self.assertNotIn(PRICE_MODEL_METADATA_KEY, llm.metadata)

    def test_no_deployment_name_at_all_raises(self) -> None:
        """
        A class-only llm_config without any deployment fails clearly instead of sending model: null.
        """
        with self.assertRaises(OpenAIError) as context:
            self._build_policy({"deployment_name": None, "model_name": None}, model_name=None)

        self.assertIn("AZURE_OPENAI_DEPLOYMENT_NAME", str(context.exception))
        # Checked in create_client() before the httpx client is opened, so nothing leaks.
        self.assertIsNone(getattr(self.policies[-1], "http_client", None))
        hint: str = ApiKeyErrorCheck.check_for_api_key_exception(context.exception)
        self.assertIn("AZURE_OPENAI_DEPLOYMENT_NAME", hint)

    def test_langchain_model_rules_follow_the_deployment_name(self) -> None:
        """
        langchain-openai keys its model rules on the chat model's model, which is the deployment. So a
        temperature set for a gpt-5 deployment with a custom name is sent as given (Azure rejects values
        other than 1), while the OpenAI model only travels in the accounting metadata.
        """
        _, llm = self._build_policy({"deployment_name": "prod-reasoning", "temperature": 0.7,
                                     "use_responses_api": False}, model_name="gpt-5.4-2026-03-05")
        payload: Dict[str, Any] = self._request_payload(llm)

        self.assertEqual(llm.model_name, "prod-reasoning")
        self.assertEqual(payload.get("model"), "prod-reasoning")
        self.assertEqual(payload.get("temperature"), 0.7)
        self.assertEqual(llm.metadata.get(PRICE_MODEL_METADATA_KEY), "gpt-5.4-2026-03-05")

    # ---- The payload ----------------------------------------------------------------------------

    def test_policy_does_not_send_n(self) -> None:
        """
        n is left unset, so the Responses API payload carries no n (the endpoint rejects it).
        """
        _, llm = self._build_policy({"use_responses_api": True})
        payload: Dict[str, Any] = self._request_payload(llm)

        self.assertIsNone(llm.n)
        self.assertNotIn("n", payload)
        self._assert_binds_to_responses_create(payload)

    def test_use_responses_api_true_builds_a_responses_payload(self) -> None:
        """
        The class default of the "openai" class (Responses API) reaches the chat model unchanged.
        """
        _, llm = self._build_policy({"use_responses_api": True})
        payload: Dict[str, Any] = self._request_payload(llm)

        self.assertIs(llm.use_responses_api, True)
        self.assertIn("input", payload)
        self.assertNotIn("messages", payload)
        self._assert_binds_to_responses_create(payload)

    def test_use_responses_api_false_builds_a_chat_completions_payload(self) -> None:
        """
        An explicit false pins Chat Completions, the escape hatch for regions and models without Responses.
        """
        _, llm = self._build_policy({"use_responses_api": False})
        payload: Dict[str, Any] = self._request_payload(llm)

        self.assertIs(llm.use_responses_api, False)
        self.assertIn("messages", payload)

    def test_store_include_and_reasoning_effort_are_forwarded(self) -> None:
        """
        The Responses-side settings the "openai" class forwards reach the payload for Azure too.
        """
        _, llm = self._build_policy({"use_responses_api": True, "store": False,
                                     "include": ["reasoning.encrypted_content"], "reasoning_effort": "low"})
        payload: Dict[str, Any] = self._request_payload(llm)

        self.assertIs(payload.get("store"), False)
        self.assertEqual(payload.get("include"), ["reasoning.encrypted_content"])
        self.assertEqual(payload.get("reasoning"), {"effort": "low"})
        self._assert_binds_to_responses_create(payload)

    def test_chat_completions_only_parameters_are_forwarded(self) -> None:
        """
        presence_penalty and friends still reach a Chat Completions request when it is pinned.
        """
        _, llm = self._build_policy({"use_responses_api": False, "presence_penalty": 0.5, "seed": 7,
                                     "stop": ["END"]})
        payload: Dict[str, Any] = self._request_payload(llm)

        self.assertEqual(payload.get("presence_penalty"), 0.5)
        self.assertEqual(payload.get("seed"), 7)
        self.assertEqual(payload.get("stop"), ["END"])

    # ---- On the wire ----------------------------------------------------------------------------

    def test_chat_completions_request_hits_v1_with_a_bearer_key_and_no_api_version(self) -> None:
        """
        A pinned Chat Completions call goes to /openai/v1/chat/completions, authenticates with the API key
        as a Bearer token (which Azure's v1 API accepts), carries the deployment as "model", sends no n and
        has no api-version query string.
        """
        _, llm = self._build_policy({"use_responses_api": False}, capture=True)

        result: AIMessage = asyncio.run(llm.ainvoke([HumanMessage("hi")]))

        self.assertIsInstance(result, AIMessage)
        self.assertEqual(len(self.requests), 1)
        request: Any = self.requests[0]
        self.assertEqual(request.url.path, "/openai/v1/chat/completions")
        self.assertEqual(request.url.query, b"")
        self.assertEqual(request.headers.get("authorization"), "Bearer " + self.API_KEY)
        body: Dict[str, Any] = self._sent_body(request)
        self.assertEqual(body.get("model"), self.DEPLOYMENT_NAME)
        self.assertNotIn("n", body)

    def test_responses_request_hits_v1_responses_with_store_false(self) -> None:
        """
        The default endpoint goes to /openai/v1/responses with the deployment as "model" and store forwarded.
        """
        _, llm = self._build_policy({"use_responses_api": True, "store": False}, capture=True)

        result: AIMessage = asyncio.run(llm.ainvoke([HumanMessage("hi")]))

        self.assertIsInstance(result, AIMessage)
        request: Any = self.requests[0]
        self.assertEqual(request.url.path, "/openai/v1/responses")
        self.assertEqual(request.url.query, b"")
        body: Dict[str, Any] = self._sent_body(request)
        self.assertEqual(body.get("model"), self.DEPLOYMENT_NAME)
        self.assertIs(body.get("store"), False)
        self.assertNotIn("n", body)

    def test_entra_token_is_sent_as_the_bearer_token(self) -> None:
        """
        A configured azure_ad_token replaces the API key in the Authorization header.
        """
        _, llm = self._build_policy({"azure_ad_token": "entra-token", "use_responses_api": False}, capture=True)

        asyncio.run(llm.ainvoke([HumanMessage("hi")]))

        self.assertEqual(self.requests[0].headers.get("authorization"), "Bearer entra-token")

    # ---- Class and bucket -----------------------------------------------------------------------

    def test_chat_model_is_plain_chat_openai_with_accounting_metadata(self) -> None:
        """
        The chat model is the stock ChatOpenAI. Its metadata tells token accounting to book the usage under
        "azure-openai" and to price it by the OpenAI model, since Azure's Responses API names the deployment
        as the response model. A deployment-only llm_config gets the bucket but no price model.
        """
        _, llm = self._build_policy({})
        _, deployment_only = self._build_policy({}, model_name=None)

        self.assertIsInstance(llm, ChatOpenAI)
        self.assertEqual(dumpd(llm).get("id")[-1], "ChatOpenAI")
        self.assertEqual(llm.metadata.get(PROVIDER_METADATA_KEY), "azure-openai")
        self.assertEqual(llm.metadata.get(PRICE_MODEL_METADATA_KEY), self.MODEL_NAME)
        self.assertEqual(deployment_only.metadata.get(PROVIDER_METADATA_KEY), "azure-openai")
        self.assertNotIn(PRICE_MODEL_METADATA_KEY, deployment_only.metadata)

    def test_usage_is_booked_under_azure_openai_and_priced_by_the_openai_model(self) -> None:
        """
        End to end through LlmTokenCallbackHandler: the canned Responses API answer names the deployment as
        its model, yet the usage lands in the "azure-openai" bucket under the OpenAI model, with its price.
        """
        _, llm = self._build_policy({"use_responses_api": True}, capture=True)
        factory: DefaultLlmFactory = DefaultLlmFactory()
        factory.load()
        handler: LlmTokenCallbackHandler = LlmTokenCallbackHandler(factory.llm_infos)

        with owning_agent_scope(handler):
            asyncio.run(llm.ainvoke([HumanMessage("hi")], config={"callbacks": [handler]}))

        self.assertNotIn("openai", handler.models_token_dict)
        self.assertNotIn(self.DEPLOYMENT_NAME, handler.models_token_dict.get("azure-openai", {}))
        entry: Dict[str, Any] = handler.models_token_dict.get("azure-openai", {}).get(self.MODEL_NAME, {})
        self.assertEqual(entry.get("successful_requests"), 1)
        self.assertGreater(entry.get("total_cost"), 0.0)
        self.assertEqual(handler.total_cost, entry.get("total_cost"))

    def test_deployment_only_usage_is_booked_by_what_the_response_names(self) -> None:
        """
        Without a model_name there is no price hint, so the response model decides: the Responses API echoes
        the deployment, which has no price, while Chat Completions names the OpenAI snapshot, which is priced.
        Both still land in the "azure-openai" bucket.
        """
        factory: DefaultLlmFactory = DefaultLlmFactory()
        factory.load()
        # A deployment name the catalogue does not know, unlike "gpt-4o", which happens to be an alias in it.
        for use_responses_api, expected_key in ((True, "my-deployment"), (False, self.MODEL_NAME)):
            with self.subTest(use_responses_api=use_responses_api):
                self.requests = []
                _, llm = self._build_policy({"use_responses_api": use_responses_api,
                                             "deployment_name": "my-deployment"}, model_name=None, capture=True)
                handler: LlmTokenCallbackHandler = LlmTokenCallbackHandler(factory.llm_infos)

                with owning_agent_scope(handler):
                    asyncio.run(llm.ainvoke([HumanMessage("hi")], config={"callbacks": [handler]}))

                entry: Dict[str, Any] = handler.models_token_dict.get("azure-openai", {}).get(expected_key, {})
                self.assertEqual(entry.get("successful_requests"), 1)
                if use_responses_api:
                    self.assertEqual(entry.get("total_cost"), 0.0)
                else:
                    self.assertGreater(entry.get("total_cost"), 0.0)

    # ---- SDK client settings --------------------------------------------------------------------

    def test_max_retries_null_leaves_the_sdk_default(self) -> None:
        """
        The SDK rejects max_retries=None with a TypeError, so a null in llm_config must be left out.
        """
        policy, _ = self._build_policy({"max_retries": None})

        self.assertEqual(policy.async_openai_client.max_retries, DEFAULT_MAX_RETRIES)

    def test_max_retries_from_llm_config_is_applied(self) -> None:
        """
        A configured max_retries reaches the SDK client.
        """
        policy, _ = self._build_policy({"max_retries": 0})

        self.assertEqual(policy.async_openai_client.max_retries, 0)

    def test_default_headers_are_merged_without_mutating_the_config(self) -> None:
        """
        Extra default_headers from llm_config are sent alongside the Azure partner User-Agent, and the
        caller's dictionary is left untouched.
        """
        configured: Dict[str, str] = {"x-unit-test": "1"}
        policy, _ = self._build_policy({"default_headers": configured})

        self.assertEqual(policy.async_openai_client.default_headers.get("x-unit-test"), "1")
        self.assertEqual(policy.async_openai_client.default_headers.get("User-Agent"),
                         "langchain-partner-python-azure-openai")
        self.assertEqual(configured, {"x-unit-test": "1"})

    def test_streaming_flags_reach_the_chat_model_and_connection_settings_stay_on_the_sdk_client(self) -> None:
        """
        streaming and stream_usage follow the llm_config; organization and timeout land on the SDK client,
        while the chat model's own copies of the connection settings stay None because a client was given.
        """
        policy, llm = self._build_policy({"streaming": True, "openai_organization": "org-1",
                                          "openai_proxy": "http://127.0.0.1:9"})

        self.assertIs(llm.streaming, True)
        self.assertIs(llm.stream_usage, True)
        self.assertIsNone(llm.openai_organization)
        self.assertIsNone(llm.openai_proxy)
        self.assertIsNone(llm.request_timeout)
        self.assertIsNone(llm.max_retries)
        self.assertEqual(policy.async_openai_client.organization, "org-1")
        self.assertEqual(policy.async_openai_client.timeout, 5)

    def test_configuration_errors_reach_the_factory_as_api_key_guidance(self) -> None:
        """
        The policy raises openai.OpenAIError for a missing credential, the family DefaultLlmFactory turns into
        the friendly API-key guidance; a plain ValueError would be reported as a bare construction error.
        """
        factory: DefaultLlmFactory = DefaultLlmFactory()
        factory.load()

        config: Dict[str, Any] = {"model_name": "azure-gpt-4o", "deployment_name": self.DEPLOYMENT_NAME}
        result: Any = factory.create_llm_with_fallbacks(config, None)

        self.assertIsInstance(result, dict)
        guidance: str = " ".join(result.get("api_key_errors"))
        self.assertIn("AZURE_OPENAI_API_KEY", guidance)
        self.assertEqual(len(result.get("construction_errors")), 0)

    # ---- Legacy keys ----------------------------------------------------------------------------

    def test_legacy_keys_are_ignored_with_a_single_warning(self) -> None:
        """
        openai_api_version, openai_api_type and model_version no longer do anything; the first llm_config
        that sets them gets one warning naming them, later ones stay quiet.
        """
        with self.assertLogs("AzureLlmPolicy", level="WARNING") as logs:
            self._build_policy({"openai_api_version": "2024-10-21", "openai_api_type": "azure"})

        self.assertEqual(len(logs.records), 1)
        self.assertIn("openai_api_version", logs.output[0])
        self.assertIn("openai_api_type", logs.output[0])

        with self.assertNoLogs("AzureLlmPolicy", level="WARNING"):
            self._build_policy({"openai_api_version": "2024-10-21"})

    def test_neutral_legacy_values_do_not_warn(self) -> None:
        """
        null and "" are what the class defaults (and older copies of them) carry; they are not worth a warning.
        """
        with self.assertNoLogs("AzureLlmPolicy", level="WARNING"):
            self._build_policy({"openai_api_type": "", "model_version": ""})

    # ---- Lifecycle ------------------------------------------------------------------------------

    def test_delete_resources_closes_the_http_client(self) -> None:
        """
        The inherited delete_resources() closes the httpx client and drops both client references.
        """
        policy, _ = self._build_policy({}, capture=True)
        http_client: Any = policy.http_client

        asyncio.run(policy.delete_resources())

        self.assertTrue(http_client.is_closed)
        self.assertIsNone(policy.http_client)
        self.assertIsNone(policy.async_openai_client)

    def test_create_llm_without_a_client_points_langchain_at_azure(self) -> None:
        """
        When create_llm() is called without a pre-built client, the clients langchain-openai builds for
        itself get the Azure credential and the v1 base URL instead of OPENAI_API_KEY and api.openai.com.
        """
        policy: AzureLlmPolicy = AzureLlmPolicy()
        self.policies.append(policy)

        llm: ChatOpenAI = policy.create_llm(dict(self.BASE_CONFIG), self.MODEL_NAME, None)

        self.assertEqual(llm.openai_api_key.get_secret_value(), self.API_KEY)
        self.assertEqual(llm.openai_api_base, self.V1_BASE_URL)
        self.assertEqual(str(llm.root_async_client.base_url), self.V1_BASE_URL)
        self.assertEqual(llm.model_name, self.DEPLOYMENT_NAME)
        self.assertEqual(llm.metadata.get(PRICE_MODEL_METADATA_KEY), self.MODEL_NAME)
