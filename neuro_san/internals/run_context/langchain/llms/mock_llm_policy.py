
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

from langchain_core.language_models.base import BaseLanguageModel

from neuro_san.internals.run_context.langchain.llms.llm_policy import LlmPolicy
from neuro_san.internals.run_context.langchain.llms.mock_chat_model import MockChatModel


class MockLlmPolicy(LlmPolicy):
    """
    LlmPolicy implementation for the MockChatModel.

    This policy creates a mock LLM for load testing that returns predefined
    responses with configurable random latency.  No external connections
    are made and no tokens are consumed.

    Supported config keys (all optional):

        responses          - A list of strings to cycle through as responses.
        min_latency        - Minimum simulated latency in seconds (default 0.1).
        max_latency        - Maximum simulated latency in seconds (default 1.5).
    """

    def create_llm(self, config: Dict[str, Any], model_name: str, client: Any) -> BaseLanguageModel:
        """
        Create a MockChatModel instance from the fully-specified llm config.

        :param config: The fully specified llm config
        :param model_name: The name of the model (unused for mock)
        :param client: The web client to use (unused for mock)
        :return: A MockChatModel instance
        """
        responses: List[str] = config.get("responses")
        min_latency: float = config.get("min_latency", 0.1)
        max_latency: float = config.get("max_latency", 1.5)

        llm = MockChatModel(
            responses=responses,
            min_latency=min_latency,
            max_latency=max_latency,
        )
        return llm

    async def delete_resources(self):
        """
        Release the run-time resources used by the model.

        MockChatModel has no network connections to clean up.
        """
        self.llm = None
