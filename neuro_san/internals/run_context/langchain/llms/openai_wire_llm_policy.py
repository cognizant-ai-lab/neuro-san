
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
See class comment for details.
"""

from typing import Any
from typing import Dict
from typing import Type

from langchain_core.language_models import BaseLanguageModel

from neuro_san.internals.run_context.langchain.llms.llm_policy import LlmPolicy
from neuro_san.internals.run_context.langchain.llms.wire.aiohttp_chat_transport import AiohttpChatTransport
from neuro_san.internals.run_context.langchain.llms.wire.chat_transport import ChatTransport
from neuro_san.internals.run_context.langchain.llms.wire.openai_wire_chat_model import OpenAiWireChatModel
from neuro_san.internals.run_context.langchain.llms.wire.pyodide_chat_transport import PyodideChatTransport


class OpenAiWireLlmPolicy(LlmPolicy):
    """
    LlmPolicy for OpenAiWireChatModel, which speaks the OpenAI-compatible
    /chat/completions protocol directly instead of going through a provider SDK.

    For runtimes the usual stack cannot reach, Pyodide in a browser above all:
    there the openai SDK's worker threads and httpx's sockets are both absent.
    See the OpenAiWireChatModel class comment for the trade that implies --
    Chat Completions only, always streaming, no Responses API.

    Which transport to use is an ordinary llm_config value rather than a
    separate policy class, so a deployment selects it the same way it selects
    anything else about a model:

        "llm_config": {
            "class": "openai-wire",
            "model_name": "gpt-4.1",
            "transport": "pyodide",
            "base_url": "/byok/v1"
        }
    """

    # The transports this policy can build, by their llm_config name. A static
    # table of imported classes, so nothing is resolved by module name at run
    # time -- that does not work in a browser bundle.
    TRANSPORT_TYPES: Dict[str, Type[ChatTransport]] = {
        "aiohttp": AiohttpChatTransport,
        "pyodide": PyodideChatTransport,
    }

    # aiohttp, because that is what works in an ordinary process. A browser
    # deployment says "pyodide" explicitly.
    DEFAULT_TRANSPORT: str = "aiohttp"

    def __init__(self, llm: BaseLanguageModel = None):
        """
        Constructor

        :param llm: An optional BaseLanguageModel this policy stands for
        """
        super().__init__(llm)
        self.transport: ChatTransport = None

    def create_client(self, config: Dict[str, Any]) -> ChatTransport:
        """
        Create the transport the chat model will move bytes through, and keep
        a reference so delete_resources() can release it.

        :param config: The fully specified llm config
        :return: The ChatTransport to hand to the chat model
        """
        transport_name: str = config.get("transport", self.DEFAULT_TRANSPORT)
        transport_type: Type[ChatTransport] = self.TRANSPORT_TYPES.get(transport_name)
        if transport_type is None:
            known = sorted(self.TRANSPORT_TYPES.keys())
            raise ValueError(f"Unknown transport '{transport_name}' in llm_config. "
                             f"Known transports are: {known}")

        self.transport = transport_type()
        return self.transport

    def create_llm(self, config: Dict[str, Any], model_name: str, client: Any) -> BaseLanguageModel:
        """
        Create the chat model that speaks the wire protocol.

        :param config: The fully specified llm config
        :param model_name: The name of the model
        :param client: The ChatTransport from create_client()
        :return: An OpenAiWireChatModel
        """
        return OpenAiWireChatModel(
            transport=client,
            base_url=self.get_value_or_env(config, "base_url", "OPENAI_BASE_URL"),
            model_name=model_name,
            api_key=self.get_value_or_env(config, "openai_api_key", "OPENAI_API_KEY"),
        )

    async def delete_resources(self):
        """
        Release the transport. The chat model holds no other resource: there is
        no SDK client underneath it to reach into, which is the point of it.
        """
        if self.transport is None:
            return
        transport: ChatTransport = self.transport
        self.transport = None
        await transport.aclose()
