
# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT

import asyncio
import logging
from time import time
from typing import Any
from typing import Dict
from typing import List
from typing import Literal
from typing import Optional
from typing_extensions import override

from langchain_community.callbacks.bedrock_anthropic_callback import MODEL_COST_PER_1K_INPUT_TOKENS
from langchain_community.callbacks.bedrock_anthropic_callback import MODEL_COST_PER_1K_OUTPUT_TOKENS
from langchain_community.callbacks.openai_info import get_openai_token_cost_for_model
from langchain_community.callbacks.openai_info import TokenType
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.messages import BaseMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGeneration, LLMResult

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

    This class is a modification of LangChain’s "UsageMetadataCallbackHandler" and "OpenAICallbackHandler":
    - https://python.langchain.com/api_reference/_modules/langchain_core/callbacks/usage.html
    #get_usage_metadata_callback
    - https://python.langchain.com/api_reference/_modules/langchain_community/callbacks/openai_info.html
    #OpenAICallbackHandler

    It collects token usage from the "usage_metadata" field of "AIMessage" each time an LLM or chat model
    finishes execution.
    The metadata is a dictionary that may include:
    - "input_tokens" (collected as "prompt_tokens")
    - "output_tokens" (collected as "completion_tokens")
    - "total_tokens"

    This handler tracks these values internally and is compatible with models that populate "usage_metadata",
    regardless of provider.

    Note:
    Token cost is calculated using prices from the LLM info file when available.
    For OpenAI, Azure OpenAI, Anthropic, and Bedrock Anthropic, there are  fallbacks to lookup tables in:
        - langchain_community.callbacks.openai_info.py
        - langchain_community.callbacks.bedrock_anthropic_callback.py
    If no price information is found, the cost defaults to 0.
    """

    # Token stats
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    successful_requests: int = 0
    total_cost: float = 0.0

    def __init__(self, llm_infos: Dict[str, Any]):
        """Initialize the CallbackHandler."""
        super().__init__()
        self._lock = asyncio.Lock()
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
            f"Total Cost (USD): ${self.total_cost}\n"
            f"Model Info: {self.models_token_dict}"
        )

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

    @override
    async def on_llm_end(self, response: LLMResult, **kwargs: Any):
        """
        Collect token usage when llm ends.
        :param response: Output from chat model
        """
        # Calculate time latency for each llm
        # Note that this will be slightly lower time taken by the agent
        time_taken_in_seconds: float = time() - self.start_time

        # Check for usage_metadata (Only work for langchain-core >= 0.2.2)
        try:
            generation = response.generations[0][0]
        except IndexError:
            generation = None

        usage_metadata: UsageMetadata = None
        response_metadata: Dict[str, Any] = None
        model_name: str = EMPTY
        if isinstance(generation, ChatGeneration):
            try:
                message = generation.message
                if isinstance(message, AIMessage):
                    # Token info is in an attribute of AIMessage called "usage_metadata".
                    usage_metadata = message.usage_metadata
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

        if usage_metadata:
            total_tokens: int = usage_metadata.get("total_tokens", 0)
            completion_tokens: int = usage_metadata.get("output_tokens", 0)
            prompt_tokens: int = usage_metadata.get("input_tokens", 0)

            # Calculate the total cost
            total_cost: float = self.calculate_token_costs(model_name, completion_tokens, prompt_tokens)

            # Update shared state behind lock
            async with self._lock:
                # Initialize model entry if this is the first time we see this model
                if model_name not in self.models_token_dict[self.provider_class]:
                    self._init_model_entry(model_name)

                # Update per-model stats.
                self.models_token_dict[self.provider_class][model_name]["total_tokens"] += total_tokens
                self.models_token_dict[self.provider_class][model_name]["prompt_tokens"] += prompt_tokens
                self.models_token_dict[self.provider_class][model_name]["completion_tokens"] += \
                    completion_tokens
                self.models_token_dict[self.provider_class][model_name]["successful_requests"] += 1
                self.models_token_dict[self.provider_class][model_name]["total_cost"] += total_cost
                self.models_token_dict[self.provider_class][model_name]["time_taken_in_seconds"] += \
                    time_taken_in_seconds

                # Update per-agent stats
                self.total_tokens += total_tokens
                self.prompt_tokens += prompt_tokens
                self.completion_tokens += completion_tokens
                self.successful_requests += 1
                self.total_cost += total_cost

    def calculate_token_costs(self, model_name: str, completion_tokens: int, prompt_tokens: int) -> float:
        """
        Calculate token costs with fallback methods for different providers.
        :param model_name: Model to calculate the cost
        :param completion_tokens: Number of output tokens
        :param prompt_tokens: Number of input tokens
        :return: Total cost
        """

        # Try to get costs from llm_infos first
        completion_token_cost: float = \
            self._get_cost_from_info(model_name, completion_tokens, "price_per_1k_output_tokens")
        prompt_token_cost: float = self._get_cost_from_info(model_name, prompt_tokens, "price_per_1k_input_tokens")

        # Fallback to provider-specific methods for anthropic and openai based models
        # Since there are lookup tables for these models in langchain-community
        if self.provider_class in ["azure-openai", "openai"]:
            completion_token_cost = completion_token_cost or \
                self._get_openai_cost(model_name, completion_tokens, token_type=TokenType.COMPLETION)
            prompt_token_cost = prompt_token_cost or \
                self._get_openai_cost(model_name, prompt_tokens, token_type=TokenType.PROMPT)

        elif self.provider_class in ["anthropic", "bedrock"]:
            completion_token_cost = completion_token_cost or \
                self._get_anthropic_cost(model_name, completion_tokens, "completion")
            prompt_token_cost = prompt_token_cost or self._get_anthropic_cost(model_name, prompt_tokens, "prompt")

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
        if model_name not in self.llm_infos:
            return None

        price = self.llm_infos.get(model_name).get(price_key)
        return (num_tokens / 1000) * price if price is not None else None

    def _get_openai_cost(self, model_name: str, num_tokens: int, token_type: TokenType) -> Optional[float]:
        """
        Get OpenAI cost with error handling.
        :param model_name: Anthorpic model to calculate the cost
        :param num_tokens: Amount of tokens
        :param token_type: Type of token, either "prompt" (input) or "completion" (output)
        :return: Token cost
        """
        try:
            return get_openai_token_cost_for_model(model_name=model_name, num_tokens=num_tokens, token_type=token_type)
        except ValueError:
            return None

    def _get_anthropic_cost(self, model_name: str, num_tokens: int, token_type: str) -> Optional[float]:
        """
        Get Anthropic/Bedrock cost with error handling.
        :param model_name: Anthorpic model to calculate the cost
        :param num_tokens: Amount of tokens
        :param token_type: Type of token, either "prompt" (input) or "completion" (output)
        :return: Token cost
        """
        try:
            return self._get_anthropic_bedrock_token_cost(model_name, num_tokens, token_type)
        except ValueError:
            return None

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
            "total_cost": 0.0,
            "time_taken_in_seconds": 0.0
        }

    def _get_anthropic_bedrock_token_cost(
            self,
            model_name: str,
            num_tokens: int,
            token_type: Literal["completion", "prompt"] = "prompt"
    ) -> float:
        """
        Calculate token cost for Anthropic/Bedrock models from the lookup table with unified logic.
        :param model_name: Anthorpic model to calculate the cost
        :param num_tokens: Amount of tokens
        :param token_type: Type of token, either "prompt" (input) or "completion" (output)
        :return: Token cost
        """

        # Normalize model name for lookup
        normalized_model: str = self._normalize_model_name(model_name)

        # Find matching model in cost tables
        # matching_models = [model for model in MODEL_COST_PER_1K_INPUT_TOKENS if normalized_model in model]
        matching_models: List[str] = []
        for model in MODEL_COST_PER_1K_INPUT_TOKENS:
            if normalized_model in model:
                matching_models.append(model)

        if not matching_models:
            error_msg = f"Unknown model: {model_name}. Known models: {', '.join(MODEL_COST_PER_1K_INPUT_TOKENS.keys())}"
            logging.warning(error_msg)
            raise ValueError(error_msg)

        if len(matching_models) > 1:
            error_msg = f"Ambiguous model name '{model_name}'. Matches: {', '.join(matching_models)}"
            logging.warning(error_msg)
            raise ValueError(error_msg)

        # Calculate cost
        full_model_id: str = matching_models[0]
        if token_type == "prompt":
            cost_table: Dict[str, float] = MODEL_COST_PER_1K_INPUT_TOKENS
        else:
            cost_table = MODEL_COST_PER_1K_OUTPUT_TOKENS

        return (num_tokens / 1000) * cost_table[full_model_id]

    def _normalize_model_name(self, model_name: str) -> str:
        """
        Normalize model name for consistent lookup across Bedrock and Anthropic formats.
        :param model_name: Full name or id of Anthropic LLM
        :return: Name for checking in the lookup table
        """
        if "anthropic" in model_name:
            # For Bedrock: extract base model from cross-region inference profile
            # e.g., 'us.anthropic.claude-3-sonnet' -> 'anthropic.claude-3-sonnet'
            parts = model_name.split(".")
            if len(parts) >= 2:
                return ".".join(parts[-2:])

        return model_name
