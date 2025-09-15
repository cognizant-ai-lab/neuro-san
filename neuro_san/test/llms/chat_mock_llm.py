
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

from typing import Any
from typing import Dict
from typing import Iterator
from typing import List
from typing import Optional

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.messages import AIMessageChunk
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.outputs import ChatResult
from pydantic import ConfigDict
from pydantic import Field
from tiktoken import get_encoding


class ChatMockLlm(BaseChatModel):
    """
    A custom chat model that echoes the input.

    Adapted from https://python.langchain.com/docs/how_to/custom_chat_model/
    """

    # This is required field and it is possible to have multiple test models.
    model_name: str = Field(default=None, alias="model")
    # Maybe useful for testing
    max_retries: Optional[int] = None

    # Accept both argument name and alias
    model_config = ConfigDict(populate_by_name=True)

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Override the _generate method to implement the chat model logic.

        This can be a call to an API, a call to a local model, or any other
        implementation that generates a response to the input prompt.

        :param messages: the prompt composed of a list of messages.
        :param stop: a list of strings on which the model should stop generating.
                  If generation stops due to a stop token, the stop token itself
                  SHOULD BE INCLUDED as part of the output. This is not enforced
                  across models right now, but it's a good practice to follow since
                  it makes it much easier to parse the output of the model
                  downstream and understand why generation stopped.
        :param run_manager: A run manager with callbacks for the LLM.

        :return: chat result containing chat generation which includes ai message.
        """

        # The last message should be human message
        last_message = messages[-1]
        content = last_message.content
        input_tokens = self._num_tokens_from_string(content)
        message = AIMessage(
            content=content,
            additional_kwargs={},  # Used to add additional payload to the message
            response_metadata={  # Use for response metadata
                "model_name": self.model_name,
            },
            usage_metadata={
                "input_tokens": input_tokens,
                "output_tokens": input_tokens,
                "total_tokens": 2*input_tokens,
            },
        )

        generation = ChatGeneration(message=message)
        return ChatResult(generations=[generation])

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """Stream the output of the model.

        This method should be implemented if the model can generate output
        in a streaming fashion.

        ***This is required for AgentExecutor.***

        Note that the _astream implementation uses run_in_executor to launch the sync _stream
        in a separate thread if _stream is implemented. Thus, it is not required to override
        the async method.

        :param messages: the prompt composed of a list of messages.
        :param stop: a list of strings on which the model should stop generating.
                  If generation stops due to a stop token, the stop token itself
                  SHOULD BE INCLUDED as part of the output. This is not enforced
                  across models right now, but it's a good practice to follow since
                  it makes it much easier to parse the output of the model
                  downstream and understand why generation stopped.
        :param run_manager: A run manager with callbacks for the LLM.
        :yields: ChatGenerationChunk objects containing the streamed model output.
        """

        # The last message should be human message
        last_message = messages[-1]
        content = last_message.content
        input_tokens = self._num_tokens_from_string(content)
        for i, content_chunk in enumerate(content):
            # This is to make input = output tokens for streaming
            if i == 0:
                output_tokens = input_tokens - len(content) + 1
            else:
                output_tokens = 1

            chunk = ChatGenerationChunk(
                message=AIMessageChunk(
                    content=content_chunk,
                    usage_metadata={
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": input_tokens + output_tokens,
                    },
                )
            )
            input_tokens = 0

            if run_manager:
                # This is optional in newer versions of LangChain
                # The on_llm_new_token will be called automatically
                run_manager.on_llm_new_token(content_chunk, chunk=chunk)

            yield chunk

        # Add model name in response metadata.
        chunk = ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                response_metadata={"model_name": self.model_name},
            )
        )
        if run_manager:
            # This is optional in newer versions of LangChain
            # The on_llm_new_token will be called automatically
            run_manager.on_llm_new_token(content, chunk=chunk)

        yield chunk

    def _num_tokens_from_string(self, string: str, encoding_name: str = "o200k_base") -> int:
        """
        Returns the number of tokens in a text string using tiktoken.
        The default encoding is the same one as gpt-4o.

        :param string: Input string.
        :param encoding_name: Encoding model to use.

        :return: Number of token.
        """
        encoding = get_encoding(encoding_name)
        num_tokens = len(encoding.encode(string))
        return num_tokens

    @property
    def _llm_type(self) -> str:
        """Get the type of language model used by this chat model."""
        return "echoing-chat-model-basic"

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        """Return a dictionary of identifying parameters.

        This information is used by the LangChain callback system, which
        is used for tracing purposes make it possible to monitor LLMs.
        """
        return {
            # The model name allows users to specify custom token counting
            # rules in LLM monitoring application.
            "model_name": self.model_name,
        }
