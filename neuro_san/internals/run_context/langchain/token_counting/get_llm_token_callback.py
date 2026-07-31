
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

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import Token
from typing import Any
from typing import Dict

from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler \
    import LlmTokenCallbackHandler
# The ContextVar (and its langchain configure-hook registration) lives with the
# handler class so the handler can consult it to attribute events to their
# owning agent.
from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler \
    import llm_token_callback_var


@contextmanager
def get_llm_token_callback(llm_infos: Dict[str, Any]) -> Generator[LlmTokenCallbackHandler, None, None]:
    """Get llm token callback.

    Get context manager for tracking usage metadata across chat model calls using
    "AIMessage.usage_metadata".

    This class is a modification of LangChain’s "UsageMetadataCallbackHandler":
    - https://python.langchain.com/api_reference/_modules/langchain_core/callbacks/usage.html
    #get_usage_metadata_callback

    :param llm_infos: Dictionary containing configuration or metadata about the LLM
                      (e.g., model name, class (provider), token cost).
    :return: A generator-based context manager that yields an `LlmTokenCallbackHandler`
             for tracking token usage within the context.
    """
    # Create a new callback handler instance for tracking token usage
    cb = LlmTokenCallbackHandler(llm_infos)

    # Set the context variable to the newly created callback handler,
    # keeping the token so the previous value can be restored on exit.
    token: Token = llm_token_callback_var.set(cb)

    try:
        # Yield the callback handler to the context block
        yield cb
    finally:
        # Restore the context variable to the value it had on entry - even if
        # the block raised.  In practice each agent scope runs its work in its
        # own copied Context (see LangChainTokenCounter.count_tokens()), so no
        # other scope ever observes this mutation, but restoring (rather than
        # clobbering to None) keeps this context manager correct on its own,
        # independent of how callers arrange their contexts.
        llm_token_callback_var.reset(token)
