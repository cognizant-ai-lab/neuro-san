
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
from typing import List
from typing import Type

import traceback

from langchain_core.callbacks.base import BaseCallbackHandler

from leaf_common.config.resolver_util import ResolverUtil


class LangfuseConfigAugmenter:
    """
    Augments Runnable configs with langfuse tracing.
    """

    def __init__(self, tracing_config: Dict[str, Any]):
        """
        Constructor
        """
        self.maybe_create_handler(tracing_config)

    def maybe_create_handler(self, tracing_config: Dict[str, Any]):
        """
        If the tracing config has a handler, create it.
        :param tracing_config: The tracing config
        """
        caller: str = "None"
        if tracing_config is not None:
            caller: str = tracing_config.get("caller", "unknown")
        print(f"langfuse_config_augmenter caller: {caller}")

        callback_handler_type: Type[BaseCallbackHandler] = None
        handler: BaseCallbackHandler = tracing_config.get("langfuse_handler")
        if handler is None:
            # See if we can create a new langfuse handler instance.
            callback_handler_type = ResolverUtil.create_type("langfuse.langchain.CallbackHandler",
                                                             raise_if_not_found=False)
            traceback.print_stack()
            print("\n\n\n")

            if callback_handler_type is None:
                # Nothing we can do. Skip.
                return None

            handler = callback_handler_type()
            tracing_config["langfuse_handler"] = handler

        print(f"using langfuse handler: {handler}")
        return handler

    def augment_config(self, runnable_config: Dict[str, Any], tracing_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Augment the callbacks with the handler.
        :param runnable_config: The config for the runnable
        :param handler: The optional handler to use
        :return: The augmented config
        """
        handler = self.maybe_create_handler(tracing_config)
        if handler is None:
            # Nothing we can do. Skip.
            return runnable_config

        # trace_id: str = handler.get_trace_id()
        # trace_id: str = "unknown"
        # print(f"    with trace_id: {trace_id}")

        # Set the callbacks per the langfuse docs
        callbacks: List[BaseCallbackHandler] = runnable_config.get("callbacks", [])
        if handler not in callbacks:
            callbacks.append(handler)
        runnable_config["callbacks"] = callbacks

        runnable_config["neuro_san_tracing_config"] = tracing_config

        # Get the run_name, which is the full name of the runnable with origin information
        # run_name: str = runnable_config.get("run_name")
        # if run_name:
        #     empty: Dict[str, Any] = {}
        #     metadata: Dict[str, Any] = runnable_config.get("metadata", empty)
        #     metadata["langfuse_trace_name"] = run_name
        #     runnable_config["metadata"] = metadata
        #     print(f"metadata: {metadata}")

        return runnable_config
