
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
from typing import Awaitable
from typing import Callable

from logging import getLogger
import traceback

from langchain_core.tools import BaseTool

from leaf_common.logging.sensitive_logger import SensitiveLogger

from neuro_san.internals.utils.exception_util import ExceptionUtil


class McpToolErrorHandler:
    """
    Holder of an async_invoke bound method that stands in for an MCP tool's
    coroutine in order to catch errors raised while calling the MCP server.
    See https://github.com/cognizant-ai-lab/neuro-san/issues/1097

    Background:
    MCP tools arrive from langchain-mcp-adapters as plain StructuredTool
    instances whose async implementation lives in their "coroutine" attribute.
    LangChain executes such a tool by calling "await tool.coroutine(**args)".
    Nothing in that stack handles errors: if the MCP call raises (an HTTP 504
    from a gateway timeout, a connection failure, or a ToolException from an
    MCP error result), the exception escapes the tool, and langgraph's ToolNode
    re-raises anything that is not a ToolInvocationError. That aborts the whole
    agent chain run, and the client receives "Agent stopped due to exception..."
    instead of an answer.

    The fix:
    LangChainMcpAdapter replaces each MCP tool's coroutine attribute with the
    async_invoke *bound method* of an instance of this class. The instance
    captures the original coroutine at construction time, and the bound method
    is a drop-in replacement for it: calling it returns an awaitable, which is
    the entire contract the coroutine attribute has to satisfy.

    It must be a real (bound) method rather than the instance itself with an
    async __call__: when building the agent, langgraph's ToolNode passes the
    tool's coroutine to typing.get_type_hints() while scanning for injected
    arguments, and get_type_hints() only accepts modules, classes, methods,
    or functions. A callable instance makes agent construction raise
    "TypeError: ... is not a module, class, method, or function"
    (observed with langgraph 1.2.9; langgraph 1.2.4 did not do this scan).

    When the tool is invoked, async_invoke awaits the original coroutine inside
    a try/except. Success passes through untouched. On failure, the exception is
    converted into a normal "Error: <message>" *return value*, so from
    langgraph's point of view the tool ran fine and simply reported an error.
    The agent chain keeps running, and the LLM can react to the failure
    (retry, rephrase, or explain it) instead of the run dying.

    This mirrors how CodedTool errors are handled in
    AbstractClassActivation.attempt_invoke(): the concise exception message
    goes back to the LLM, while the full traceback stays in the server logs only.
    """

    def __init__(self, tool: BaseTool):
        """
        Constructor

        Captures the tool's original coroutine, so instances must be created
        *before* their async_invoke method is assigned as the tool's coroutine.
        If the assignment happened first, self.original_coroutine would refer
        back to async_invoke itself and recurse forever.

        :param tool: The MCP-backed LangChain tool whose coroutine is to be wrapped.
                The tool itself is kept (not just its coroutine) because error
                reporting needs its name and response_format at call time.
        """
        self.tool: BaseTool = tool
        self.original_coroutine: Callable[..., Awaitable[Any]] = tool.coroutine
        # Exception messages and tracebacks can carry sensitive request data,
        # so route them through a SensitiveLogger, which respects the
        # LEAF_LOG_SENSITIVE env var setting.
        self.sensitive_logger: SensitiveLogger = SensitiveLogger(getLogger(self.__class__.__name__))

    async def async_invoke(self, *args, **kwargs) -> Any:
        """
        Invoke the original tool coroutine, converting any exception into
        a concise "Error: ..." tool output.

        LangChain calls this with only the tool arguments produced by the LLM,
        exactly as it would have called the original coroutine.

        :return: Whatever the original coroutine returns, or an error string
                (paired with a None artifact when the tool's response_format
                is "content_and_artifact") if the call raised.
        """
        try:
            return await self.original_coroutine(*args, **kwargs)
        # Catch everything: transport failures surface as httpx exceptions, MCP
        # error results as ToolException, and we cannot enumerate what else a
        # given server might raise. Note that asyncio.CancelledError derives
        # from BaseException, so timeout cancellation still propagates.
        # pylint: disable=broad-exception-caught
        except Exception as exception:
            # Keep the full traceback in the server logs only;
            # the client-facing tool output is the concise message below.
            self.sensitive_logger.error("Error invoking MCP tool %s: %s", self.tool.name, str(exception))
            self.sensitive_logger.error("%s", traceback.format_exc())
            # Transport failures reach us wrapped in an ExceptionGroup by anyio,
            # whose str() is just "unhandled errors in a TaskGroup (N sub-exceptions)".
            # get_exception_details() recursively unwraps such groups so the LLM
            # sees the real cause (e.g. "ConnectError: All connection attempts
            # failed") rather than the unhelpful group summary.
            error_output: str = f"Error: {ExceptionUtil.get_exception_details(exception).rstrip()}"
            if self.tool.response_format == "content_and_artifact":
                # Tools from langchain-mcp-adapters are built with
                # response_format="content_and_artifact", for which LangChain
                # requires a (content, artifact) 2-tuple as the return value.
                return error_output, None
            return error_output
