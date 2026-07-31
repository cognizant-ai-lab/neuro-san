
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
from typing import Any
from typing import Dict

from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler \
    import LlmTokenCallbackHandler
# Re-exported for backwards compatibility: the ContextVar (and its langchain
# configure-hook registration) lives with the handler class so the handler can
# consult it to attribute events to their owning agent.
# pylint: disable=unused-import
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

    # Set the context variable to the newly created callback handler
    llm_token_callback_var.set(cb)

    # Yield the callback handler to the context block
    yield cb

    # Reset the context variable to None when the context exits
    llm_token_callback_var.set(None)
