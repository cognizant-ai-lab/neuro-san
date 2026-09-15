
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

from contextlib import contextmanager

from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler import LlmTokenCallbackHandler
from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler import llm_token_callback_var


@contextmanager
def owning_agent_scope(handler: LlmTokenCallbackHandler):
    """
    Simulate the agent scope that owns the LLM call being handled.

    In production, each agent's count_tokens() sets llm_token_callback_var to its
    own handler, so at event time the var holds the handler of the nearest
    enclosing agent scope.  The handler consults it to tell its own agent's LLM
    calls apart from downstream agents' calls it also hears about.
    """
    token = llm_token_callback_var.set(handler)
    try:
        yield
    finally:
        llm_token_callback_var.reset(token)
