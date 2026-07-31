
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

from asyncio import Lock as AsyncLock
from contextvars import ContextVar
import logging
from time import time
from typing import Any
from typing import Dict
from typing import Optional
from typing import Tuple
from typing_extensions import override

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.messages import BaseMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_core.tracers.context import register_configure_hook

# Each agent's token counting scope sets this ContextVar to its own handler
# (see get_llm_token_callback()).  register_configure_hook() below makes langchain
# attach the ContextVar's current value to every run as an *inheritable* callback,
# so an agent's handler also receives events for LLM calls made by any downstream
# agents it calls.  At event time the ContextVar holds the handler of the *nearest*
# enclosing agent scope, which is what lets a handler tell its own agent's LLM
# calls apart from downstream ones (see LlmTokenCallbackHandler._is_own_call()).
llm_token_callback_var: ContextVar[Optional["LlmTokenCallbackHandler"]] = (
        ContextVar("llm_token_callback", default=None)
    )
register_configure_hook(llm_token_callback_var, inheritable=True)

EMPTY = ""
CLASS_TABLE = {
    # Chat model class : Provider class
    "AzureChatOpenAI": "azure-openai",
    "ChatAnthropic": "anthropic",
    "ChatBedrock": "bedrock",
    "ChatGoogleGenerativeAI": "gemini",
    "ChatNVIDIA": "nvidia",
    "ChatOllama": "ollama",
    "ChatOpenAI": "openai",
}


# pylint: disable=too-many-ancestors
# pylint: disable=too-many-instance-attributes
class LlmTokenCallbackHandler(AsyncCallbackHandler):
    """
    Callback handler that tracks token usage via "AIMessage.usage_metadata".

    This class is a modification of LangChain’s:
    - "UsageMetadataCallbackHandler" in langchain_core.callbacks.usage
    - "OpenAICallbackHandler" in langchain_community.callbacks.openai_info, from the sunset
      langchain-community package (repository archived at https://github.com/langchain-ai/langchain-community)

    It collects token usage from the "usage_metadata" field of "AIMessage" each time an LLM or chat model
    finishes execution.
    The metadata is a dictionary that may include:
    - "input_tokens" (collected as "prompt_tokens")
    - "output_tokens" (collected as "completion_tokens")
    - "total_tokens"

    This handler tracks these values internally and is compatible with models that populate "usage_metadata",
    regardless of provider.

    Attribution semantics:
    Because handlers are registered as inheritable langchain callbacks (see llm_token_callback_var above),
    one instance receives events both for its own agent's LLM calls and for calls made by downstream
    agents.  The two kinds of tallies kept here treat those differently:
    - The scalar totals ("total_tokens", "successful_requests", etc.) count *every* event received,
      so they are cumulative over the agent's whole subtree.  These feed the per-agent accounting
      messages, where a front man's totals cover the entire request.
    - "models_token_dict" only counts the agent's *own* LLM calls (see _is_own_call()), so that
      LangChainTokenCounter.report() can merge each agent's contribution into the request-wide
      accounting with every LLM call counted exactly once, no matter how deeply agents nest.

    Note:
    Token cost is calculated using prices from the LLM info file
    ("price_per_1k_input_tokens" / "price_per_1k_output_tokens") when available.
    If no price information is found, the cost defaults to 0 and a warning is logged.
    """

    # Token stats
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    successful_requests: int = 0
    empty_responses: int = 0
    total_cost: float = 0.0

    def __init__(self, llm_infos: Dict[str, Any]):
        """Initialize the CallbackHandler."""
        super().__init__()
        self._lock = AsyncLock()
        self.llm_infos: Dict[str, Any] = llm_infos
        self.provider_class: str = None
        self.start_time: float = None

        # Dictionary for accumulating token stats of models. For example
        # {"openai": {"gpt-4o": {"total_tokens": 100, "prompt_tokens": 80, ...}, "gpt_4.1": {...}}, }
        # Note that models with the same name but different providers counts as different models.
        self.models_token_dict: Dict[str, Any] = {}

    @override
    def __repr__(self) -> str:
        return (
            f"Tokens Used: {self.total_tokens}\n"
            f"\tPrompt Tokens: {self.prompt_tokens}\n"
            f"\tCompletion Tokens: {self.completion_tokens}\n"
            f"Successful Requests: {self.successful_requests}\n"
            f"Empty Responses: {self.empty_responses}\n"
            f"Total Cost (USD): ${self.total_cost}\n"
            f"Model Info: {self.models_token_dict}"
        )

    def _is_own_call(self) -> bool:
        """
        :return: True if the event being handled belongs to an LLM call made by this
                handler's own agent.  False for calls made by downstream agents, whose
                events this handler also receives because handlers are inheritable
                callbacks.  At event time, llm_token_callback_var holds the handler
                of the nearest enclosing agent scope - the call's owner.
        """
        return llm_token_callback_var.get() is self

    @override
    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        **kwargs: Any
    ):
        """
        Extract the LLM class and start timer when chat model starts.
        :param serialized: Dictionary of metadata of the invoked model
        """
        if not self._is_own_call():
            # A downstream agent's chat model is starting.  Only that agent's own
            # handler tracks per-model state for it.
            return

        # Chat moddel class of the LLM is in the last item of the id list
        chat_model_class: str = serialized.get("id")[-1]
        # Match the chat model class with neuro-san model class
        self.provider_class = CLASS_TABLE.get(chat_model_class)
        # If no match found, use chat model class instead
        if not self.provider_class:
            self.provider_class = chat_model_class
        if self.provider_class not in self.models_token_dict:
            self.models_token_dict[self.provider_class] = {}

        # Start timer
        self.start_time = time()

    @staticmethod
    def _extract_usage(response: LLMResult) -> Tuple[UsageMetadata, str, bool]:
        """
        Pull usage information out of an LLMResult.
        :param response: Output from chat model
        :return: A tuple of (usage_metadata, model_name, is_empty_response).
                usage_metadata is None when the response carries none.
        """
        # Check for usage_metadata (Only work for langchain-core >= 0.2.2)
        try:
            generation = response.generations[0][0]
        except IndexError:
            generation = None

        usage_metadata: UsageMetadata = None
        response_metadata: Dict[str, Any] = None
        model_name: str = EMPTY
        is_empty_response: bool = False
        if isinstance(generation, ChatGeneration):
            try:
                message = generation.message
                if isinstance(message, AIMessage):
                    # Token info is in an attribute of AIMessage called "usage_metadata".
                    usage_metadata = message.usage_metadata
                    is_empty_response = LlmTokenCallbackHandler._is_empty_response(message)
                    # Get model name so that cost can be determined if needed.
                    response_metadata = message.response_metadata
                    if response_metadata:
                        if "model_name" in response_metadata:
                            model_name = response_metadata.get("model_name")
                        elif "model_id" in response_metadata:
                            model_name = response_metadata.get("model_id")
                        elif "model" in response_metadata:
                            model_name = response_metadata.get("model")
            except AttributeError:
                pass

        return usage_metadata, model_name, is_empty_response

    @override
    async def on_llm_end(self, response: LLMResult, **kwargs: Any):
        """
        Collect token usage when llm ends.
        :param response: Output from chat model
        """
        # Per-model stats are only tracked for this agent's own LLM calls.
        # Downstream agents' calls still contribute to the scalar subtree totals below.
        is_own_call: bool = self._is_own_call()

        # Calculate time latency for each llm
        # Note that this will be slightly lower time taken by the agent
        # The timer is only started (on_chat_model_start) for this agent's own calls.
        time_taken_in_seconds: float = 0.0
        if is_own_call and self.start_time is not None:
            time_taken_in_seconds = time() - self.start_time

        usage_metadata, model_name, is_empty_response = self._extract_usage(response)

        if usage_metadata:
            total_tokens: int = usage_metadata.get("total_tokens", 0)
            completion_tokens: int = usage_metadata.get("output_tokens", 0)
            prompt_tokens: int = usage_metadata.get("input_tokens", 0)

            # Calculate the total cost
            total_cost: float = self.calculate_token_costs(model_name, completion_tokens, prompt_tokens)

            # Update shared state behind lock
            async with self._lock:
                if is_own_call:
                    # Initialize model entry if this is the first time we see this model
                    if model_name not in self.models_token_dict[self.provider_class]:
                        self._init_model_entry(model_name)

                    # Update per-model stats (this agent's own calls only).
                    self.models_token_dict[self.provider_class][model_name]["total_tokens"] += total_tokens
                    self.models_token_dict[self.provider_class][model_name]["prompt_tokens"] += prompt_tokens
                    self.models_token_dict[self.provider_class][model_name]["completion_tokens"] += \
                        completion_tokens
                    self.models_token_dict[self.provider_class][model_name]["successful_requests"] += 1
                    self.models_token_dict[self.provider_class][model_name]["empty_responses"] += \
                        int(is_empty_response)
                    self.models_token_dict[self.provider_class][model_name]["total_cost"] += total_cost
                    self.models_token_dict[self.provider_class][model_name]["time_taken_in_seconds"] += \
                        time_taken_in_seconds

                # Update per-agent stats (own + downstream agents' calls)
                self.total_tokens += total_tokens
                self.prompt_tokens += prompt_tokens
                self.completion_tokens += completion_tokens
                self.successful_requests += 1
                self.empty_responses += int(is_empty_response)
                self.total_cost += total_cost

    def calculate_token_costs(self, model_name: str, completion_tokens: int, prompt_tokens: int) -> float:
        """
        Calculate token costs from prices in the LLM info file.
        :param model_name: Model to calculate the cost
        :param completion_tokens: Number of output tokens
        :param prompt_tokens: Number of input tokens
        :return: Total cost
        """
        completion_token_cost: Optional[float] = \
            self._get_cost_from_info(model_name, completion_tokens, "price_per_1k_output_tokens")
        prompt_token_cost: Optional[float] = \
            self._get_cost_from_info(model_name, prompt_tokens, "price_per_1k_input_tokens")

        if completion_token_cost is None and prompt_token_cost is None:
            logging.warning("No price info found for model %s in llm info. Token cost defaults to 0.", model_name)

        # Return total cost
        return (completion_token_cost or 0.0) + (prompt_token_cost or 0.0)

    def _get_cost_from_info(self, model_name: str, num_tokens: int, price_key: str) -> Optional[float]:
        """
        Get cost from llm_infos if available.
        :param model_name: Model to calculate the cost
        :param num_tokens: Amount of tokens
        :param price_key: keyword to look in llm info for price
        :return: Token cost
        """
        llm_info: Dict[str, Any] = self.llm_infos.get(model_name)
        if llm_info is None:
            return None

        price: Optional[float] = llm_info.get(price_key)

        # Alias entries (e.g. "gpt-5.2") carry no price of their own; fall back to the
        # concrete model they point to via "use_model_name" (e.g. "gpt-5.2-2025-12-11").
        if price is None:
            use_model_name: Optional[str] = llm_info.get("use_model_name")
            if use_model_name is not None:
                price = self.llm_infos.get(use_model_name, {}).get(price_key)

        return (num_tokens / 1000) * price if price is not None else None

    def _init_model_entry(self, model_name: str):
        """
        Initialize a new model entry in the tracking dictionary.
        :param model_name: LLM model name to put in the dictionary
        """
        self.models_token_dict[self.provider_class][model_name] = {
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "successful_requests": 0,
            "empty_responses": 0,
            "total_cost": 0.0,
            "time_taken_in_seconds": 0.0
        }

    @staticmethod
    def _is_blank_content_block(item: Any) -> bool:
        """
        Determine whether a single list-content item carries no visible text.
        :param item: One element of an AIMessage's list content
        :return: True for a whitespace-only string or an empty/whitespace text
                 block ({"type": "text"}); any other block type counts as content
        """
        if isinstance(item, str):
            return item.strip() == EMPTY
        if isinstance(item, dict) and item.get("type") == "text":
            return str(item.get("text", EMPTY)).strip() == EMPTY
        return False

    @staticmethod
    def _is_empty_response(message: AIMessage) -> bool:
        """
        Determine whether an AIMessage carried no actionable output, i.e. neither
        text content nor a tool call. Such a response still counts as a successful
        request, so it is tracked separately as "empty_responses".
        :param message: The AIMessage returned by the chat model
        :return: True if the message has no content and no tool calls
        """
        content: Any = message.content
        if isinstance(content, str):
            has_content: bool = content.strip() != EMPTY
        elif isinstance(content, list):
            has_content = not all(
                LlmTokenCallbackHandler._is_blank_content_block(item) for item in content
            )
        else:
            has_content = bool(content)
        return not has_content and not getattr(message, "tool_calls", None)
