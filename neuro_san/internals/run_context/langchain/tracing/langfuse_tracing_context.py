
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
from typing import List
from typing import Type

from datetime import datetime
from socket import gethostname
import traceback

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.runnables.base import Runnable

from leaf_common.config.resolver_util import ResolverUtil

from neuro_san.internals.interfaces.run_target import RunTarget
from neuro_san.internals.interfaces.tracing_context import TracingContext
from neuro_san.internals.run_context.langchain.tracing.langchain_tracing_context import LangChainTracingContext


class LangfuseTracingContext(LangChainTracingContext):
    """
    TracingContext implementation for runs that use Langfuse.
    """

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

        self.parent_context: LangfuseTracingContext = parent_context
        self.callback_handler: BaseCallbackHandler = None
        self.main_span: Any = None

        # See if we can get a langfuse handler instance.
        handler_type = ResolverUtil.create_type("langfuse.langchain.CallbackHandler", raise_if_not_found=False)
        if handler_type is None:
            raise ValueError("""
Failed to create Langfuse CallbackHandler. Try one of the following:

If you really wanted to use langfuse for observability, you can install it with
    pip install langfuse

If you didn't mean to use langfuse for observability, you can do this:
    export LANGFUSE_ENABLED=false
""")

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
        # Get the user_id for the trace
        empty: Dict[str, Any] = {}
        request_metadata: Dict[str, Any] = runnable_config.get("metadata", empty)
        user_id: str = request_metadata.get("user_id", "<Unknown>")

        # Create a session_id for the trace.
        # It's possible we should move the addition of hostname up to the services infra.
        request_id: str = request_metadata.get("request_id", "<Unknown>")
        now: datetime = datetime.now()
        session_id: str = f"{request_id}@{now.strftime('%Y-%m-%d-%H:%M:%S.%f')}"
        hostname: str = gethostname()
        session_id: str = f"{session_id}@{hostname}"

        # pylint: disable=import-outside-toplevel
        from langfuse import propagate_attributes

        # Weird: Langfuse docs here ...
        #   https://langfuse.com/docs/observability/features/users
        # ... say to use the with/ContextManager here, but pylint doesn't like it.
        # It works. :shrug:
        # According to langfuse docs, this should be safe for use in async code.
        # pylint: disable=not-context-manager
        print(f"using main_span as context manager: {self.main_span}")
        with self.main_span:
            print("with main_span")
            with propagate_attributes(user_id=user_id, session_id=session_id):
                print("with propagate_attributes")
                await super().ainvoke(chain, inputs, runnable_config)

    def create_main_span(self, runnable_config: Dict[str, Any]):
        """
        Create the main span for the run
        :param runnable_config: The config for the runnable
        """

        if self.main_span is not None:
            return

        run_name: str = runnable_config.get("run_name")

        # We have a handler, therefore we have langfuse installed.
        # No need to ResolverUtil absolutely everything, but we still need to locally import
        # for the rest of the system to behave without langfuse installed.

        # pylint: disable=import-outside-toplevel
        from langfuse import get_client

        print(f"about to get main_span with run_name: {run_name}")
        if self.parent_context is not None:
            # Get the langfuse client
            print("Parent context is not none")
            parent_span: Any = self.parent_context.main_span
            print(f"Using parent context main_span as basis {parent_span} type {parent_span.__class__.__name__}")
            # self.main_span = parent_span.start_as_current_observation(run_name, as_type="span")
            langfuse_client: Any = get_client()
            self.main_span = langfuse_client.start_as_current_observation(as_type="span", name=run_name)
        else:
            # Get the langfuse client
            print("parent context is none")
            langfuse_client: Any = get_client()
            self.main_span = langfuse_client.start_as_current_observation(as_type="agent", name=run_name)
        print(f"main_span: {self.main_span}")

    def maybe_create_handler(self, runnable_config: Dict[str, Any]):
        """
        If the tracing config doesn't have a handler, create it.
        """
        self.create_main_span(runnable_config)

        if self.callback_handler is None and self.parent_context is not None:
            self.callback_handler = self.parent_context.callback_handler

        if self.callback_handler is None:
            _ = traceback
            # traceback.print_stack()
            print("\n\n")

            # See if we can create a new langfuse handler instance.
            callback_handler_type: Type[BaseCallbackHandler] = None
            callback_handler_type = ResolverUtil.create_type("langfuse.langchain.CallbackHandler",
                                                             raise_if_not_found=False)
            if callback_handler_type is None:
                # Nothing we can do. Skip.
                self.callback_handler = None
                return

            print(f"about to create langfuse handler with main_span: {self.main_span}")
            self.callback_handler = callback_handler_type()

        print(f"using langfuse handler: {self.callback_handler}")

    def augment_config(self, runnable_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Augment the callbacks with the handler.
        :param runnable_config: The config for the runnable
        :return: The augmented config
        """
        self.maybe_create_handler(runnable_config)
        if self.callback_handler is None:
            # Nothing we can do. Skip.
            return runnable_config

        # Set the callbacks per the langfuse docs
        callbacks: List[BaseCallbackHandler] = runnable_config.get("callbacks", [])
        if self.callback_handler not in callbacks:
            callbacks.append(self.callback_handler)
        runnable_config["callbacks"] = callbacks

        runnable_config["neuro_san_tracing_context"] = self

        return runnable_config
