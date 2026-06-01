
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
from typing import Optional

import os

from logging import Logger
from logging import getLogger

from pydantic import ConfigDict
from typing_extensions import override

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.messages.base import BaseMessage
from langchain_core.messages.base import messages_to_dict
from langchain_core.runnables.base import Other
from langchain_core.runnables.base import RunnableConfig
from langchain_core.runnables.passthrough import RunnablePassthrough
from langchain_core.runnables.utils import Input
from langchain_core.runnables.utils import Output

from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.interfaces.run_target import RunTarget
from neuro_san.internals.interfaces.tracing_context import TracingContext
from neuro_san.internals.journals.intercepting_journal import InterceptingJournal
from neuro_san.internals.messages.origination import Origination
from neuro_san.internals.utils.metadata_util import MetadataUtil


class NeuroSanRunnable(RunnablePassthrough, RunTarget):
    """
    RunnablePassthrough implementation that intercepts journal messages
    for a particular origin.
    """

    # Declarations of member variables here satisfy Pydantic style,
    # which is a type validator that langchain is based on which
    # is able to use JSON schema definitions to validate fields.
    invocation_context: InvocationContext = None

    interceptor: InterceptingJournal = None

    origin: List[Dict[str, Any]] = None

    session_id: str = None

    # Default logger
    logger: Optional[Logger] = None

    run_target: Optional[RunTarget] = None

    tracing_context: Optional[TracingContext] = None

    # This guy needs to be a pydantic class and in order to have
    # any non-pydantic non-serializable members, we need to do this.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(
        self,
        **kwargs: Any,
    ) -> None:
        """
        Constructor
        """
        # Use the run_target from the kwargs as the afunc parameter
        # for the RunnablePassthrough.  If that doesn't exist, assume
        # our own run_it() method is overridden and use that.
        run_target: RunTarget = kwargs.get("run_target", self)
        super().__init__(afunc=run_target.run_it, **kwargs)

        self.logger: Logger = getLogger(self.__class__.__name__)

    # pylint: disable=redefined-builtin
    @override
    async def ainvoke(
        self,
        input: Other,
        config: RunnableConfig | None = None,
        **kwargs: Any | None,
    ) -> Other:

        # Run afunc (run_it) inside _acall_with_config so it gets a real run_manager.
        # RunnablePassthrough.ainvoke invokes afunc raw and only wraps a no-op identity
        # in _acall_with_config, which leaves child ainvoke calls inside run_it() (the
        # agent_chain, etc.) without a parent_run_id pointing at this runnable. Wrapping
        # afunc directly collapses the empty wrapper span and lets children nest under
        # this runnable in the trace.
        await self._acall_with_config(self.afunc, input, config, **kwargs)

        # Collect intercepted outputs to report back to the tracing infrastructure.
        outputs: Dict[str, Any] = self.get_intercepted_outputs()
        return outputs

    async def run_it(self, inputs: Input) -> Output:
        """
        Transform a single input into an output.

        Args:
            inputs: The input to the `Runnable`.

        Returns:
            The output of the `Runnable`.
        """
        raise NotImplementedError

    def prepare_runnable_config(self, session_id: str = None,
                                callbacks: List[BaseCallbackHandler] = None,
                                recursion_limit: int = None,
                                use_run_name: bool = False) -> Dict[str, Any]:
        """
        Prepare a RunnableConfig for a Runnable invocation.  See:
        https://python.langchain.com/api_reference/core/runnables/langchain_core.runnables.config.RunnableConfig.html

        :param session_id: An id for the run
        :param callbacks: A list of BaseCallbackHandlers to use for the run
        :param recursion_limit: Maximum number of times a call can recurse.
        :return: A dictionary to be used for a Runnable's invoke config.
        """
        agent_name: str = self.invocation_context.get_agent_name()

        # Set up a run name for tracing purposes
        run_name: str = None
        if use_run_name:

            agent_prefix: str = ""
            if agent_name:
                agent_prefix = agent_name

            origin_name: str = ""
            if self.origin:
                full_name: str = Origination.get_full_name_from_origin(self.origin)
                origin_name = f"{full_name}"

            delimiter: str = ""
            if agent_prefix and origin_name:
                delimiter = ":"

            run_name: str = f"{agent_prefix}{delimiter}{origin_name}"

        runnable_config: Dict[str, Any] = {}

        # Add some optional stuff
        if session_id:
            runnable_config["configurable"] = {
                "session_id": session_id
            }

        if run_name:
            runnable_config["run_name"] = run_name

        if callbacks:
            runnable_config["callbacks"] = callbacks

        if recursion_limit:
            runnable_config["recursion_limit"] = recursion_limit

        # Only add metadata if we have something
        runnable_metadata: Dict[str, Any] = self.prepare_tracing_metadata()
        if runnable_metadata:
            runnable_config["metadata"] = runnable_metadata

        # Augment the config per the TracingContext
        if self.tracing_context:
            runnable_config = self.tracing_context.augment_config(runnable_config)

        return runnable_config

    def prepare_tracing_metadata(self) -> Dict[str, Any]:
        """
        Prepare a dictionary of metadata for tracing purposes.

        :return: A dictionary of metadata for run tracing
        """
        runnable_metadata: Dict[str, Any] = {}

        # Add values for listed env vars if they have values.
        # Defaults are standard env vars for kubernetes deployments
        env_vars_str: str = os.getenv("AGENT_TRACING_METADATA_ENV_VARS",
                                      "POD_NAME POD_NAMESPACE POD_IP NODE_NAME")
        to_add: Dict[str, Any] = MetadataUtil.minimize_metadata(os.environ, env_vars_str)
        runnable_metadata.update(to_add)

        request_keys: str = os.getenv("AGENT_TRACING_METADATA_REQUEST_KEYS",
                                      os.getenv("AGENT_USAGE_LOGGER_METADATA",
                                                os.getenv("AGENT_FORWARDED_REQUEST_METADATA",
                                                          "request_id user_id")))
        request_metadata: Dict[str, Any] = self.invocation_context.get_metadata()
        to_add: Dict[str, Any] = MetadataUtil.minimize_metadata(request_metadata, request_keys)
        runnable_metadata.update(to_add)

        return runnable_metadata

    def get_intercepted_outputs(self) -> Dict[str, Any]:
        """
        :return: the intercepted outputs
        """
        intercepted_messages: List[BaseMessage] = self.interceptor.get_messages()

        messages: List[Dict[str, Any]] = messages_to_dict(intercepted_messages)
        outputs: Dict[str, Any] = {
            "messages": messages
        }
        return outputs
