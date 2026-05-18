
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

from datetime import datetime
from socket import gethostname

from langchain_core.runnables.base import Runnable

from leaf_common.config.resolver_util import ResolverUtil

from neuro_san.internals.interfaces.run_target import RunTarget
from neuro_san.internals.run_context.langchain.tracing.langchain_tracing_context import LangChainTracingContext
from neuro_san.internals.run_context.langchain.tracing.langfuse_config_augmenter import LangfuseConfigAugmenter


class LangFuseLangChainTracingContext(LangChainTracingContext):
    """
    RunTarget interface for a TracingContext in langchain with LangFuse tracing hooks.
    """

    def __init__(self, run_target: RunTarget, config: Dict[str, Any]):
        """
        Constructor

        :param run_target: The RunTarget instance to be traced
        :param config: The configuration for the tracing context
        """
        super().__init__(run_target=run_target, config=config)

        # See if we can get a langfuse handler instance.
        handler_type = ResolverUtil.create_type("langfuse.langchain.CallbackHandler", raise_if_not_found=False)
        if handler_type is None:
            raise ValueError("""
Failed to create LangFuse CallbackHandler. Try one of the following:

If you really wanted to use langfuse for observability, you can install it with
    pip install langfuse

If you didn't mean to use langfuse for observability, you can do this:
    export LANGFUSE_ENABLED=false
""")

        self.tracing_config["caller"] = "langfuse_langchain_tracing_context"
        config_augmenter: LangfuseConfigAugmenter = LangfuseConfigAugmenter(self.tracing_config)
        config_augmenter.maybe_create_handler(self.tracing_config)

    async def ainvoke(self, chain: Runnable, inputs: Any, runnable_config: Dict[str, Any]):
        """
        Invoke the chain with the inputs and config
        :param chain: The chain to invoke
        :param inputs: The inputs to the chain
        :param runnable_config: The config for the runnable
        """
        # Augment the callbacks with the handler.
        config_augmenter: LangfuseConfigAugmenter = LangfuseConfigAugmenter(self.tracing_config)
        runnable_config = config_augmenter.augment_config(runnable_config, self.tracing_config)

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

        # We have a handler, therefore we have langfuse installed.
        # No need to ResolverUtil absolutely everything, but we still need to locally import
        # for the rest of the system to behave without langfuse installed.

        # pylint: disable=import-outside-toplevel
        from langfuse import propagate_attributes

        # Weird: Langfuse docs here ...
        #   https://langfuse.com/docs/observability/features/users
        # ... say to use the with/ContextManager here, but pylint doesn't like it.
        # It works. :shrug:
        # According to langfuse docs, this should be safe for use in async code.
        # pylint: disable=not-context-manager
        with propagate_attributes(user_id=user_id, session_id=session_id):
            await super().ainvoke(chain, inputs, runnable_config)
