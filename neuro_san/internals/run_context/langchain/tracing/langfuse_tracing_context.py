
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
from __future__ import annotations

from typing import Any
from typing import Dict
from typing import Type

from contextvars import ContextVar
from datetime import datetime
from socket import gethostname

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.runnables.base import Runnable
from langchain_core.tracers.context import register_configure_hook

from leaf_common.config.resolver_util import ResolverUtil

from neuro_san.internals.interfaces.run_target import RunTarget
from neuro_san.internals.interfaces.tracing_context import TracingContext
from neuro_san.internals.run_context.langchain.tracing.langchain_tracing_context import LangChainTracingContext


class LangfuseTracingContext(LangChainTracingContext):
    """
    TracingContext implementation for runs that use Langfuse.
    """

    @staticmethod
    def register():
        """
        Globally register the Langfuse CallbackHandler, if available
        This is really the only way we can do this with langchain managing span parentage.
        """

        # Create a context variable for the langfuse handler
        context_var = ContextVar("langfuse_handler", default=None)

        # See if we can create a new langfuse handler instance.
        callback_handler_type: Type[BaseCallbackHandler] = None
        callback_handler_type = ResolverUtil.create_type("langfuse.langchain.CallbackHandler",
                                                         raise_if_not_found=False)
        if callback_handler_type is not None:

            # Create the callback handler instance
            callback_handler: BaseCallbackHandler = callback_handler_type()

            # Register the callback handler via the context variable
            context_var.set(callback_handler)
            register_configure_hook(context_var, inheritable=True)

        return context_var

    # Global context variable for the langfuse callback handler.
    # Do the register() once at class load time.
    HANDLER_CONTEXT_VAR: ContextVar = register()

    def __init__(self, run_target: RunTarget,
                 config: Dict[str, Any],
                 parent_context: LangfuseTracingContext = None):
        """
        Constructor

        :param run_target: The RunTarget instance to be traced
        :param config: The configuration for the tracing context
        :param parent_context: The parent instance to riff from.
        """
        super().__init__(run_target=run_target, config=config)

        # Keep a reference to the parent context
        self.parent_context: LangfuseTracingContext = parent_context

        # Keep a session_id for any child TracingContext to use in its langfuse config for the run.
        self.session_id: str = None

        # See if we can get a langfuse handler instance.
        # handler_type = ResolverUtil.create_type("langfuse.langchain.CallbackHandler", raise_if_not_found=False)
        # if handler_type is None:
        if self.HANDLER_CONTEXT_VAR.get() is None:
            raise ValueError("""
Failed to create Langfuse CallbackHandler. Try one of the following:

If you really wanted to use langfuse for observability, you can install it with
    pip install langfuse

If you didn't mean to use langfuse for observability, you can do this:
    export LANGFUSE_ENABLED=false
""")

        # Keep track of some Langfuse state

        # No need to ResolverUtil absolutely everything, but we still need to locally import
        # for the rest of the system to behave without langfuse installed.
        # pylint: disable=import-outside-toplevel
        from langfuse import Langfuse
        from langfuse import get_client
        from opentelemetry.util._decorator import _AgnosticContextManager

        self.langfuse_client: Langfuse = get_client()
        self.main_span: _AgnosticContextManager[Any] = None

    def clone(self) -> TracingContext:
        """
        Creates a copy the tracing context.

        :return: A clone of the tracing context.
        """
        clone = LangfuseTracingContext(run_target=self.run_target, config=self.config, parent_context=self)
        return clone

    async def ainvoke(self, chain: Runnable, inputs: Any, runnable_config: Dict[str, Any]):
        """
        Invoke the chain with the inputs and config
        :param chain: The chain to invoke
        :param inputs: The inputs to the chain
        :param runnable_config: The config for the runnable
        """
        if self.main_span is not None:
            # We have a main span. Use it as the context.
            # pylint: disable=not-context-manager
            with self.main_span:
                await super().ainvoke(chain, inputs, runnable_config)
        else:
            await super().ainvoke(chain, inputs, runnable_config)

    def create_main_span(self, runnable_config: Dict[str, Any]):
        """
        Create the main span for the run
        :param runnable_config: The config for the runnable
        """

        if self.main_span is not None:
            # Already done
            return

        if self.langfuse_client is None:
            # Langfuse is not enabled
            return

        if self.parent_context is not None and self.parent_context.main_span is not None:
            # We have a parent context with a main_span. Dont do anything.
            return

        run_name: str = runnable_config.get("run_name")

        # This "agent" type gets us the nice little icon in the langfuse UI
        # According to langfuse docs, this should be safe for use in async code.
        self.main_span = self.langfuse_client.start_as_current_observation(as_type="agent", name=run_name)

    def augment_config(self, runnable_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Augment the configuration however the implementation sees fit (if at all).
        :param runnable_config: The config for the runnable
        :return: The augmented config
        """
        self.create_main_span(runnable_config)

        runnable_config["neuro_san_tracing_context"] = self

        # Get the user_id for the trace
        empty: Dict[str, Any] = {}
        request_metadata: Dict[str, Any] = runnable_config.get("metadata", empty)
        user_id: str = request_metadata.get("user_id", "<Unknown>")
        run_name = runnable_config.get("run_name")

        # Find the right session_id to use for the session components
        self.session_id: str = self.get_parent_session_id()
        if self.session_id is None:

            # Get pieces of the session_id to construct
            request_id: str = request_metadata.get("request_id", "<Unknown>")

            # It's possible we should move the addition of hostname up to the services infra.
            hostname: str = gethostname()

            # We use the time to distiguish sessions on a restarted server on the same host.
            now_str: str = datetime.now().strftime('%Y-%m-%d-%H:%M:%S.%f')

            # Create a session_id for the trace.
            self.session_id: str = f"{run_name}@{request_id}@{hostname}@{now_str}"

        elif run_name is not None:
            # Add .agent to the end to get langfuse to display the agent icon
            new_name: str = f"{run_name} (agent)"
            runnable_config["run_name"] = new_name

        request_metadata["langfuse_user_id"] = user_id
        request_metadata["langfuse_session_id"] = self.session_id
        runnable_config["metadata"] = request_metadata

        return runnable_config

    def get_parent_session_id(self):
        """
        Get the parent session id.
        We want the to be consistent for any depth of trace in the request.

        :return: The parent session id
        """
        if self.parent_context is not None:
            return self.parent_context.get_parent_session_id()

        return self.session_id

    async def flush(self):
        """
        Flush the tracing context.
        """
        if self.langfuse_client is not None:
            self.langfuse_client.flush()
