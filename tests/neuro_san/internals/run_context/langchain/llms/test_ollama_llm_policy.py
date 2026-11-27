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

from typing import Any
from typing import Dict
from unittest import TestCase
from unittest.mock import patch

from typing_extensions import override

from leaf_common.resolution.resolver import Resolver

from neuro_san.internals.run_context.langchain.llms.default_llm_factory import DefaultLlmFactory
from neuro_san.internals.run_context.langchain.llms.ollama_llm_policy import OllamaLlmPolicy
from neuro_san.internals.utils.neuro_san_config import NeuroSanConfig


class TestOllamaLlmPolicy(TestCase):
    """
    Test cases for OllamaLlmPolicy.

    The chat model is built exactly the way production does (llm_config overlaid on the
    ollama class args by DefaultLlmFactory, then create_llm()) and the result is inspected.
    Constructing ChatOllama makes no network call. langchain-ollama is an optional
    dependency, so the tests resolve it lazily and skip themselves when it is absent.
    """

    MODEL_NAME: str = "llama3.1"

    @override
    def setUp(self) -> None:
        """
        Pins the environment and loads the stock default_llm_info.hocon.

        AGENT_LLM_INFO_FILE is removed so that a deployer override present in the environment
        cannot change the class args these tests check.
        """
        environment: Dict[str, str] = {}
        for name, value in os.environ.items():
            if name != "AGENT_LLM_INFO_FILE":
                environment[name] = value

        # Cleanups run last-in first-out, so this reload sees the restored environment.
        self.addCleanup(NeuroSanConfig.reset_for_testing)
        env_patcher: Any = patch.dict(os.environ, environment, clear=True)
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        NeuroSanConfig.reset_for_testing()

        self.factory: DefaultLlmFactory = DefaultLlmFactory()
        self.factory.load()

    def _build_llm(self, extra_config: Dict[str, Any]) -> Any:
        """
        Builds the chat model the way production does.

        :param extra_config: llm_config keys layered on top of the model name
        :return: The ChatOllama instance create_llm() returned
        """
        # No install_if_missing here: a unit test must never install packages.
        chat_model_class: Any = Resolver().resolve_class_in_module("ChatOllama",
                                                                   module_name="langchain_ollama",
                                                                   raise_if_not_found=False)
        if chat_model_class is None:
            self.skipTest("langchain-ollama not installed")

        llm_config: Dict[str, Any] = {
            "class": "ollama",
            "model_name": self.MODEL_NAME,
        }
        llm_config.update(extra_config)
        config: Dict[str, Any] = self.factory.create_full_llm_config(llm_config, {})

        llm: Any = OllamaLlmPolicy().create_llm(config, config["model_name"], None)
        self.assertIsInstance(llm, chat_model_class)
        return llm

    def test_max_tokens_sets_num_predict(self):
        """
        max_tokens caps the output when num_predict is not set.

        The ollama class args declare num_predict as null, so the full config always
        carries the key and the fallback to max_tokens has to treat null as unset.
        """
        llm: Any = self._build_llm({"max_tokens": 1024})
        self.assertEqual(1024, llm.num_predict)

    def test_num_predict_wins_over_max_tokens(self):
        """
        An explicit num_predict takes precedence over max_tokens.
        """
        llm: Any = self._build_llm({"num_predict": 256, "max_tokens": 1024})
        self.assertEqual(256, llm.num_predict)

    def test_no_cap_leaves_num_predict_unset(self):
        """
        Without num_predict or max_tokens, Ollama keeps its own default.
        """
        llm: Any = self._build_llm({})
        self.assertIsNone(llm.num_predict)
