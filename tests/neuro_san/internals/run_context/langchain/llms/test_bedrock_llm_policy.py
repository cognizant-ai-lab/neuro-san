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

import asyncio
import os

from typing import Any
from typing import Dict
from typing import List
from typing import Tuple
from unittest import TestCase
from unittest.mock import patch

from typing_extensions import override

from leaf_common.resolution.resolver import Resolver

from neuro_san.internals.run_context.langchain.llms.bedrock_llm_policy import BedrockLlmPolicy
from neuro_san.internals.run_context.langchain.llms.default_llm_factory import DefaultLlmFactory
from neuro_san.internals.run_context.langchain.llms.llm_policy import LlmPolicy


class TestBedrockLlmPolicy(TestCase):
    """
    Test cases for BedrockLlmPolicy.create_llm().

    Each test builds the chat model the way production does: DefaultLlmFactory overlays the
    llm_config on the "bedrock" class args from default_llm_info.hocon, and the policy builds the
    chat model from the result. Building it only creates boto3 clients, so nothing here calls AWS.

    langchain-aws is an optional dependency, so the chat model class is resolved lazily and the
    tests skip themselves when it is not installed.
    """

    # A plain Bedrock model id. Building a chat model for it makes no AWS call.
    MODEL_NAME: str = "mistral.mistral-large-2407-v1:0"

    @override
    def setUp(self) -> None:
        """
        Pins the environment, loads the stock default_llm_info.hocon and starts tracking policies.

        AGENT_LLM_INFO_FILE and every AWS variable are removed so that neither a deployer override
        nor a local AWS setup can change what these tests build. Dummy AWS keys are then set so that
        boto3 never searches for real credentials.
        """
        # patch.dict restores the whole environment on stop(), including the variables removed below.
        env_patcher: Any = patch.dict(os.environ)
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

        # Loop over a copy of the names because the loop removes entries from os.environ.
        name: str
        for name in list(os.environ):
            if name.startswith("AWS_") or name == "AGENT_LLM_INFO_FILE":
                os.environ.pop(name)
        os.environ["AWS_ACCESS_KEY_ID"] = "test-access-key-id"
        os.environ["AWS_SECRET_ACCESS_KEY"] = "test-secret-access-key"

        # Loaded after the environment is pinned so the stock hocon is what gets read.
        self.factory: DefaultLlmFactory = DefaultLlmFactory()
        self.factory.load()

        # Every policy a test builds goes here so tearDown() can close its boto3 clients.
        self.policies: List[LlmPolicy] = []

        # Resolves the optional chat model class the same way LlmPolicy does, so that a missing
        # package skips the tests instead of failing the module import.
        self.resolver: Resolver = Resolver()

    @override
    def tearDown(self) -> None:
        """
        Closes the boto3 clients of every policy a test built.
        """
        # Each policy holds the clients of the one chat model it built.
        policy: LlmPolicy
        for policy in self.policies:
            asyncio.run(policy.delete_resources())

    def _build_llm(self, extra_config: Dict[str, Any]) -> Any:
        """
        Builds the chat model for a "bedrock" llm_config the way production does.

        :param extra_config: llm_config keys layered on top of the class, model and region
        :return: The ChatBedrock instance the policy built
        """
        # No install_if_missing here: a unit test must never install packages.
        chat_model_class: Any = self.resolver.resolve_class_in_module("ChatBedrock",
                                                                      module_name="langchain_aws",
                                                                      raise_if_not_found=False)
        if chat_model_class is None:
            self.skipTest("langchain-aws not installed")

        # The region is required to create the boto3 clients.
        llm_config: Dict[str, Any] = {
            "class": "bedrock",
            "model_name": TestBedrockLlmPolicy.MODEL_NAME,
            "region_name": "us-east-1",
        }
        llm_config.update(extra_config)
        config: Dict[str, Any] = self.factory.create_full_llm_config(llm_config, {})

        policy: BedrockLlmPolicy = BedrockLlmPolicy()
        # Registered first so that tearDown() closes the clients even when a check below fails.
        self.policies.append(policy)

        components: Tuple[Any, LlmPolicy] = policy.create_llm_resources_components(config)
        llm: Any = components[0]
        self.assertIsInstance(llm, chat_model_class)
        return llm

    def test_model_kwargs_reach_the_chat_model(self) -> None:
        """
        "model_kwargs" in llm_config lands on the chat model, which adds them to each request.
        """
        model_kwargs: Dict[str, Any] = {"top_k": 50}

        llm: Any = self._build_llm({"model_kwargs": model_kwargs})

        self.assertEqual(model_kwargs, llm.model_kwargs)

    def test_model_kwargs_null_default_is_accepted(self) -> None:
        """
        Without "model_kwargs" in llm_config the class default null is passed on,
        and the chat model treats it as no extra parameters.
        """
        llm: Any = self._build_llm({})

        self.assertEqual({}, llm.model_kwargs)
