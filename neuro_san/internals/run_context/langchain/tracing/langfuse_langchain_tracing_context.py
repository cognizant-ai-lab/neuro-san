
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

from datetime import datetime
from socket import gethostname

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.runnables.base import Runnable

from leaf_common.config.resolver_util import ResolverUtil

from neuro_san.internals.run_context.langchain.tracing.langchain_tracing_context import LangChainTracingContext


class LangFuseLangChainTracingContext(LangChainTracingContext):
    """
    RunTarget interface for a TracingContext in langchain with LangFuse tracing hooks.
    """

    async def ainvoke(self, chain: Runnable, inputs: Any, runnable_config: Dict[str, Any]):
        """
        Invoke the chain with the inputs and config
        :param chain: The chain to invoke
        :param inputs: The inputs to the chain
        :param runnable_config: The config for the runnable
        """

        # See if we can get a langfuse handler instance.
        handler = ResolverUtil.create_instance("langfuse.langchain.CallbackHandler", "langfuse", BaseCallbackHandler)
        if handler is None:
            raise ValueError("""
Failed to create LangFuse CallbackHandler. Try one of the following:

If you really wanted to use langfuse for observability, you can install it with
    pip install langfuse

If you didn't mean to use langfuse for observability, you can do this:
    export LANGFUSE_ENABLED=false
""")

        # Set the callbacks per the langfuse docs
        callbacks: List[BaseCallbackHandler] = runnable_config.get("callbacks", [])
        callbacks.append(handler)
        runnable_config["callbacks"] = callbacks

        # Get the user_id for the trace
        request_metadata: Dict[str, Any] = runnable_config.get("metadata")
        user_id: str = request_metadata.get("user_id")

        # Create a session_id for the trace.
        # It's possible we should move the addition of hostname up to the services infra.
        request_id: str = request_metadata.get("request_id")
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
