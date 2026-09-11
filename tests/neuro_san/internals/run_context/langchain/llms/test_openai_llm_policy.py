
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

from typing import Any
from typing import Dict
from typing import Iterator
from typing import List
from typing import Optional
from typing import Tuple

import pytest

from langchain_core.messages import HumanMessage
from langchain_openai.chat_models.base import ChatOpenAI
from openai.resources.responses import AsyncResponses

from neuro_san.internals.run_context.langchain.llms.openai_llm_policy import OpenAILlmPolicy


class TestOpenAILlmPolicy:
    """
    Test cases for OpenAILlmPolicy.create_llm().

    These tests build the ChatOpenAI exactly the way production does (create_client()
    followed by create_llm()) and then inspect what was built, without ever making
    a network call.
    """

    # Points at a closed local port so that an accidental network call fails fast instead
    # of reaching a real OpenAI endpoint. The key is a dummy; see the policies fixture.
    BASE_CONFIG: Dict[str, Any] = {
        "openai_api_key": "sk-test",
        "openai_api_base": "http://127.0.0.1:9",
        "max_retries": 0,
        "request_timeout": 5,
        "streaming": False,
    }

    # Every environment variable create_llm() consults for a connection setting, mapped to
    # the llm_config key that must be consulted alongside it. See issue #1308.
    EXPECTED_KEYS_BY_ENV: Dict[str, str] = {
        "OPENAI_API_KEY": "openai_api_key",
        "OPENAI_API_BASE": "openai_api_base",
        "OPENAI_ORG_ID": "openai_organization",
        "OPENAI_PROXY": "openai_proxy",
    }

    @pytest.fixture(name="policies")
    def fixture_policies(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[List[OpenAILlmPolicy]]:
        """
        Collects every OpenAILlmPolicy a test builds and releases their httpx clients afterwards.

        ChatOpenAI also builds a synchronous client from the OPENAI_API_KEY environment variable,
        so the variable is pinned to a dummy value here to guarantee no real key is ever used.

        :param monkeypatch: The pytest fixture used to override the environment
        :return: A list that tests append their policies to; each one is cleaned up on teardown
        """
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        created: List[OpenAILlmPolicy] = []
        yield created
        for policy in created:
            asyncio.run(policy.delete_resources())

    def _build_llm(self, policies: List[OpenAILlmPolicy], extra_config: Dict[str, Any],
                   model_name: str = "gpt-5.2") -> ChatOpenAI:
        """
        Builds a ChatOpenAI the way production does: create_client() then create_llm().

        :param policies: The fixture list that tracks policies for teardown
        :param extra_config: llm_config keys layered on top of BASE_CONFIG
        :param model_name: The OpenAI model name to build the llm for
        :return: The ChatOpenAI instance produced by OpenAILlmPolicy.create_llm()
        """
        config: Dict[str, Any] = dict(self.BASE_CONFIG)
        config.update(extra_config)

        policy: OpenAILlmPolicy = OpenAILlmPolicy()
        # Register before creating anything so teardown still runs if create_llm() raises.
        policies.append(policy)

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
        Asserts that the payload only uses keyword arguments the Responses API create() accepts.

        Binding against the real SDK signature is what fails with "unexpected keyword argument 'n'"
        when n leaks into a Responses API request, which is the exact symptom of issue #725.

        :param payload: The request payload to check
        """
        signature: inspect.Signature = inspect.signature(AsyncResponses.create)
        # The leading None stands in for "self" because create is inspected as an unbound method.
        signature.bind(None, **payload)

    def test_default_config_keeps_chat_completions_without_n(self, policies: List[OpenAILlmPolicy]) -> None:
        """
        A plain gpt-5.2 config stays on Chat Completions, does not force an endpoint, and no longer sends n.

        :param policies: The fixture list that tracks policies for teardown
        """
        llm: ChatOpenAI = self._build_llm(policies, {})
        payload: Dict[str, Any] = self._request_payload(llm)

        assert llm.n is None
        assert "n" not in payload
        # None (not False) is what keeps langchain's auto-routing alive for existing configs.
        assert llm.use_responses_api is None
        assert llm._use_responses_api(llm._default_params) is False
        assert "messages" in payload

    def test_reasoning_dict_auto_routes_to_responses_api_without_n(self, policies: List[OpenAILlmPolicy]) -> None:
        """
        Regression test for issue #725: a "reasoning" dict makes langchain auto-route to the
        Responses API, and the resulting payload must be acceptable to that API (no n).

        create_llm() used to pass n=1 unconditionally. Chat Completions tolerates that, but the
        Responses API has no n parameter, so any config that langchain auto-routed there failed
        client-side. The fix drops n and forwards "use_responses_api" so agents can pick the endpoint.

        :param policies: The fixture list that tracks policies for teardown
        """
        llm: ChatOpenAI = self._build_llm(policies, {"reasoning": {"effort": "low"}})
        payload: Dict[str, Any] = self._request_payload(llm)

        assert llm.use_responses_api is None
        assert llm._use_responses_api(llm._default_params) is True
        assert "n" not in payload
        assert payload["reasoning"] == {"effort": "low"}
        self._assert_binds_to_responses_create(payload)

    def test_use_responses_api_true_is_forwarded(self, policies: List[OpenAILlmPolicy]) -> None:
        """
        An explicit "use_responses_api": true reaches ChatOpenAI and produces a Responses API payload.

        :param policies: The fixture list that tracks policies for teardown
        """
        llm: ChatOpenAI = self._build_llm(policies, {"use_responses_api": True})
        payload: Dict[str, Any] = self._request_payload(llm)

        assert llm.use_responses_api is True
        assert llm._use_responses_api(llm._default_params) is True
        # The Responses API takes "input" where Chat Completions takes "messages".
        assert "input" in payload
        assert "messages" not in payload
        assert "n" not in payload
        self._assert_binds_to_responses_create(payload)

    def test_use_responses_api_false_is_forwarded_as_false(self, policies: List[OpenAILlmPolicy]) -> None:
        """
        An explicit "use_responses_api": false reaches ChatOpenAI as False, not as None.

        :param policies: The fixture list that tracks policies for teardown
        """
        llm: ChatOpenAI = self._build_llm(policies, {"use_responses_api": False})
        payload: Dict[str, Any] = self._request_payload(llm)

        assert llm.use_responses_api is False
        assert llm._use_responses_api(llm._default_params) is False
        assert "messages" in payload

    def test_use_responses_api_false_overrides_auto_routing(self, policies: List[OpenAILlmPolicy]) -> None:
        """
        An explicit false pins Chat Completions even when a "reasoning" dict would otherwise
        auto-route to the Responses API. This is why the key must not go through get_bool():
        an absent key collapsed to False would disable auto-routing for everyone.

        :param policies: The fixture list that tracks policies for teardown
        """
        llm: ChatOpenAI = self._build_llm(policies, {"use_responses_api": False,
                                                     "reasoning": {"effort": "low"}})
        payload: Dict[str, Any] = self._request_payload(llm)

        assert llm.use_responses_api is False
        assert llm._use_responses_api(llm._default_params) is False
        assert "messages" in payload

    def test_reasoning_effort_folds_into_reasoning_on_responses_api(self, policies: List[OpenAILlmPolicy]) -> None:
        """
        On the Responses API path langchain rewrites reasoning_effort into reasoning.effort.

        :param policies: The fixture list that tracks policies for teardown
        """
        llm: ChatOpenAI = self._build_llm(policies, {"reasoning_effort": "low", "use_responses_api": True})
        payload: Dict[str, Any] = self._request_payload(llm)

        assert payload["reasoning"] == {"effort": "low"}
        assert "reasoning_effort" not in payload
        assert "n" not in payload
        self._assert_binds_to_responses_create(payload)

    def test_create_llm_uses_matching_config_keys(self, policies: List[OpenAILlmPolicy],
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
        """
        Regression test for issue #1308: every environment variable that create_llm() consults
        must be paired with its own llm_config key. In particular OPENAI_PROXY must be paired
        with "openai_proxy"; it used to be paired with "openai_organization".

        The test records every (config key, env key) pair that create_llm() hands to
        get_value_or_env() and checks each pairing against EXPECTED_KEYS_BY_ENV.

        :param policies: The fixture list that tracks policies for teardown
        :param monkeypatch: The pytest fixture used to swap in the recording get_value_or_env()
        """
        recorded: List[Tuple[str, Optional[str]]] = []

        # pylint: disable=unused-argument
        def recorder(config: Dict[str, Any], key: str, env_key: Optional[str],
                     none_obj: Any = None) -> None:
            """
            Stand-in for EnvironmentConfiguration.get_value_or_env() that records
            which (key, env_key) pair was requested and always returns None.

            :param config: The llm config being consulted (unused; only the pairing matters)
            :param key: The config key being requested
            :param env_key: The environment variable being requested, if any
            :param none_obj: Optional object whose presence would normally short-circuit
                             the lookup (unused; only the pairing matters)
            """
            # Returning None (implicitly) makes ChatOpenAI fall back to its own defaults,
            # so nothing recorded here influences how the client is built.
            recorded.append((key, env_key))
        # pylint: enable=unused-argument

        config: Dict[str, Any] = dict(self.BASE_CONFIG)

        policy: OpenAILlmPolicy = OpenAILlmPolicy()
        # Register before creating anything so teardown still runs if create_llm() raises.
        policies.append(policy)

        # Build the real async client first so that its own get_value_or_env()
        # lookups are not mixed into what we record from create_llm().
        client: Any = policy.create_client(config)

        # get_value_or_env() is a staticmethod on the EnvironmentConfiguration base
        # class, so shadow it on the subclass with another staticmethod; that way
        # self.get_value_or_env(...) inside create_llm() reaches the recorder.
        monkeypatch.setattr(OpenAILlmPolicy, "get_value_or_env", staticmethod(recorder))

        llm: ChatOpenAI = policy.create_llm(config, "gpt-5.2", client)
        assert llm is not None

        # Every recorded env var must have been paired with its own config key.
        seen_env_keys: List[str] = []
        for key, env_key in recorded:
            if env_key in self.EXPECTED_KEYS_BY_ENV:
                seen_env_keys.append(env_key)
                expected_key: str = self.EXPECTED_KEYS_BY_ENV[env_key]
                assert key == expected_key, \
                    f"{env_key} was looked up with config key {key!r}, expected {expected_key!r}"

        # Guard against passing vacuously if create_llm() ever stops consulting
        # get_value_or_env() for one of these settings.
        for env_key in self.EXPECTED_KEYS_BY_ENV:
            assert env_key in seen_env_keys, f"create_llm() never consulted {env_key}"

        # The exact mispairing from issue #1308 must never reappear.
        assert ("openai_organization", "OPENAI_PROXY") not in recorded

    def test_create_llm_without_client_reads_each_connection_key(self, policies: List[OpenAILlmPolicy]) -> None:
        """
        Regression test for issue #1308 at the level of the built ChatOpenAI: with no pre-built
        client, each connection setting in llm_config must land on its own ChatOpenAI field.
        Before the fix the organization id was handed to ChatOpenAI as the proxy URL.

        :param policies: The fixture list that tracks policies for teardown
        """
        config: Dict[str, Any] = dict(self.BASE_CONFIG)
        config["openai_organization"] = "org-test"
        # A closed local port, like openai_api_base, so nothing can reach a real proxy.
        config["openai_proxy"] = "http://127.0.0.1:9"

        policy: OpenAILlmPolicy = OpenAILlmPolicy()
        policies.append(policy)

        # No client is passed, so create_llm() must fall back to the llm_config values themselves.
        llm: ChatOpenAI = policy.create_llm(config, "gpt-5.2", None)

        assert llm.openai_api_key.get_secret_value() == "sk-test"
        assert llm.openai_api_base == "http://127.0.0.1:9"
        assert llm.openai_organization == "org-test"
        assert llm.openai_proxy == "http://127.0.0.1:9"
