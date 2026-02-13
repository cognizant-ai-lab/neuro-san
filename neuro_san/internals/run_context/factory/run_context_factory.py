
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

from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.run_context.factory.master_llm_factory import MasterLlmFactory
from neuro_san.internals.run_context.interfaces.run_context import RunContext
from neuro_san.internals.run_context.interfaces.tool_caller import ToolCaller
from neuro_san.internals.run_context.langchain.core.langchain_run_context import LangChainRunContext


class RunContextFactory:
    """
    Creates the correct kind of RunContext
    """

    @staticmethod
    def create_run_context(parent_run_context: RunContext,
                           tool_caller: ToolCaller,
                           invocation_context: InvocationContext = None,
                           chat_context: Dict[str, Any] = None,
                           config: Dict[str, Any] = None) \
            -> RunContext:
        """
        Creates an appropriate RunContext

        :param parent_run_context: The parent RunContext (if any) to pass
                             down its resources to a new RunContext created by
                             this call.
        :param tool_caller: The ToolCaller whose lifespan matches that
                            of the newly created RunContext
        :param invocation_context: The context policy container that pertains to the invocation
                    of the agent.
        :param chat_context: A ChatContext dictionary that contains all the state necessary
                to carry on a previous conversation, possibly from a different server.
        :param config: The config dictionary which may or may not contain
                       keys for the context_type and default llm_config
        """

        # Initialize return value
        run_context: RunContext = None

        empty: Dict[str, Any] = {}
        use_config: Dict[str, Any] = config
        if use_config is None:
            use_config = empty

        # Get some fields from the config with reasonable defaults
        default_llm_config: Dict[str, Any] = {
            # need to change this default to gpt-5.2 #730
            "model_name": "gpt-4o",
            "verbose": False
        }
        default_llm_config = use_config.get("llm_config") or default_llm_config

        # Prepare for sanity in checks below
        context_type: str = MasterLlmFactory.get_context_type(use_config)

        use_invocation_context: InvocationContext = invocation_context
        if use_invocation_context is None and parent_run_context is not None:
            use_invocation_context = parent_run_context.get_invocation_context()

        if context_type.startswith("openai"):
            raise ValueError("OpenAI Assistants implementation is no longer supported by OpenAI.")

        if context_type.startswith("langchain"):
            run_context = LangChainRunContext(default_llm_config, parent_run_context,
                                              tool_caller, use_invocation_context,
                                              chat_context)
        else:
            # Default case
            run_context = LangChainRunContext(default_llm_config, parent_run_context,
                                              tool_caller, use_invocation_context,
                                              chat_context)

        return run_context
