
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

from collections.abc import Callable
from collections.abc import Iterable
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union
from typing_extensions import override

from langchain.agents.middleware.summarization import DEFAULT_SUMMARY_PROMPT
from langchain.agents.middleware.summarization import SummarizationMiddleware
from langchain.agents.middleware.types import AgentState
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages.base import BaseMessage
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.messages.utils import MessageLikeRepresentation

from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.messages.agent_message import AgentMessage

# NOTE:
# The following defaults mirror LangChain's internal summarization defaults
# as of langchain==1.2.19. They are defined locally
# to avoid importing private module-level constants (e.g.,
# `_DEFAULT_MESSAGES_TO_KEEP`, `_DEFAULT_TRIM_TOKEN_LIMIT`), which are not
# part of the public API and may change across LangChain versions.
_DEFAULT_MESSAGES_TO_KEEP: int = 4
_DEFAULT_TRIM_TOKEN_LIMIT: int = 3000


class NeuroSanSummarizationMiddleware(SummarizationMiddleware):
    """
    Neuro-san-specific wrapper around LangChain's SummarizationMiddleware.

    This middleware monitors the chat history and triggers summarization when
    configured thresholds (e.g., message count or token count) are exceeded.

    Unlike the base implementation, this class does NOT rely on LangChain to
    manage chat state. Instead, it synchronizes the summarized output back into
    Neuro-san's own chat history and journal system.

    Key behaviors:
    - Triggers summarization based on `trigger` thresholds.
    - Preserves recent context using the `keep` policy.
    - Ensures message continuity (e.g., AI/Tool message pairing).
    - Replaces Neuro-san's chat history with the summarized result.
    - Writes a summary marker message into the journal.

    Note:
        The base SummarizationMiddleware modifies LangChain-managed state.
        Since Neuro-san manages its own chat history, this subclass adapts
        the output accordingly.

    Reference:
        https://reference.langchain.com/python/langchain/agents/middleware/summarization/SummarizationMiddleware
    """

    # pylint: disable=too-many-arguments
    def __init__(
            self,
            *,
            model: Union[str, BaseChatModel],
            origin: List[Dict[str, Any]],
            chat_history: List[BaseMessage],
            base_journal: Journal,
            trigger: Union[Tuple[str, Union[int, float]], List[Tuple[str, Union[int, float]]]] = None,
            keep: Tuple[str, Union[int, float]] = ("messages", _DEFAULT_MESSAGES_TO_KEEP),
            token_counter: Callable[[Iterable[MessageLikeRepresentation]], int] = count_tokens_approximately,
            summary_prompt: str = DEFAULT_SUMMARY_PROMPT,
            trim_tokens_to_summarize: Optional[int] = _DEFAULT_TRIM_TOKEN_LIMIT,
            **deprecated_kwargs: Any,
    ) -> None:
        """
        Initialize summarization middleware.
        :param model: Language model used to generate summaries. Passed to `init_chat_model`.
                    See https://reference.langchain.com/python/langchain/chat_models/base/init_chat_model
        :param origin: A list of dictionaries containing origin information as to which agent
                    is creating the middleware.
        :param chat_history: The chat history of the RunContext that the middleware is being created for.
        :param base_journal: The base Journal for the RunContext that the middleware is being created for.
        :param trigger: One or more thresholds that trigger summarization. (default: None)
        :param keep: Context retention policy applied after summarization.
                    (default: ("messages", _DEFAULT_MESSAGES_TO_KEEP))
        :param token_counter: Function to count tokens in messages. (default: count_tokens_approximately)
        :param summary_prompt: Prompt template for generating summaries. (default: DEFAULT_SUMMARY_PROMPT)
        :param trim_tokens_to_summarize: Maximum tokens to keep when preparing messages for
                the summarization call. (default: _DEFAULT_TRIM_TOKEN_LIMIT)
        """
        super().__init__(
            model=model, trigger=trigger, keep=keep, token_counter=token_counter, summary_prompt=summary_prompt,
            trim_tokens_to_summarize=trim_tokens_to_summarize, **deprecated_kwargs
        )
        self.origin: List[Dict[str, Any]] = origin
        self.chat_history: List[BaseMessage] = chat_history
        self.base_journal: Journal = base_journal

    @override
    async def abefore_model(
        self, state: AgentState[Any], runtime: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Hook executed before model invocation.

        If summarization is triggered, this method:
        1. Delegates summarization to the base middleware.
        2. Replaces Neuro-san's chat history with the summarized result.
        3. Writes a summary marker into the journal.

        :param state: The agent state.
        :param runtime: The runtime environment.

        :return: An updated state with summarized messages if summarization was performed.
        """
        messages_dict: Dict[str, Any] = await super().abefore_model(state, runtime)

        # No summarization occurred
        if not messages_dict:
            return None

        # Replace Neuro-san chat history with summarized messages
        self.chat_history.clear()
        # The first message is a LangChain-specific RemoveMessage instruction,
        # which is not applicable in Neuro-san, so it is skipped.
        summarized_messages: List[BaseMessage] = messages_dict.get("messages", [])
        self.chat_history.extend(summarized_messages[1:])

        # Record a marker in the journal indicating that a summary follows.
        # The actual summarized content is written separately via the
        # JournalCallbackHandler during LLM completion.
        await self.base_journal.write_message(
            message=AgentMessage("Here is a summary of the conversation to date:"),
            # Exclude current middleware origin
            origin=self.origin[:-1]
        )

        return messages_dict
