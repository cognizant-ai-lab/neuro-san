
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
"""
RemoteToolActivation - invoke a server-side coded tool over HTTP at its origin.

This is the "fetch() back to the server" piece of the Agent Web model. The
DistributableNetworkScrubber rewrites server-side `class:` references in the
wire form into `coded_tool_url`s pointing at the origin's per-tool RPC
endpoint; when a runtime ("browser") loads that network and the LLM calls
this tool, RemoteToolActivation handles the round trip.

The activation is also useful server-side: a server-resident network can
reference another origin's tool via a `coded_tool_url` and call it directly,
without standing up a full chat session over there.

See docs/agent_web_design.md (§5.5) for details.
"""
import json
from typing import Any
from typing import Dict
from typing import Optional

from logging import getLogger
from logging import Logger

import aiohttp
from langchain_core.messages.ai import AIMessage
from langchain_core.messages.base import BaseMessage

from neuro_san.internals.graph.activations.abstract_callable_activation import AbstractCallableActivation
from neuro_san.internals.graph.activations.sly_data_redactor import SlyDataRedactor
from neuro_san.internals.graph.interfaces.agent_tool_factory import AgentToolFactory
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.messages.agent_message import AgentMessage
from neuro_san.internals.run_context.factory.run_context_factory import RunContextFactory
from neuro_san.internals.run_context.interfaces.run_context import RunContext


# How long we will wait for a single tool RPC to complete.
DEFAULT_REMOTE_TOOL_TIMEOUT_SECONDS: float = 60.0


class RemoteToolActivation(AbstractCallableActivation):
    """
    CallableActivation that invokes a coded tool living on another server,
    addressed by `coded_tool_url`, via the POST /api/v1/{net}/tool/{name}
    RPC endpoint defined by the Agent Web protocol.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self,
                 parent_run_context: RunContext,
                 factory: AgentToolFactory,
                 arguments: Dict[str, Any],
                 agent_tool_spec: Dict[str, Any],
                 sly_data: Dict[str, Any]):
        """
        :param parent_run_context: Parent RunContext to pass resources down from.
        :param factory: The factory creating tools.
        :param arguments: Tool arguments passed in by the LLM.
        :param agent_tool_spec: The agent spec from the wire config; must contain
                "coded_tool_url" and may contain "allow.to_downstream" /
                "allow.from_downstream" rules.
        :param sly_data: Sly-data dict for this invocation.
        """
        super().__init__(factory, agent_tool_spec, sly_data)
        self.run_context: RunContext = RunContextFactory.create_run_context(parent_run_context, self)
        self.journal: Journal = self.run_context.get_journal()
        self.arguments: Dict[str, Any] = arguments or {}
        self.logger: Logger = getLogger(self.__class__.__name__)

        url: Optional[str] = agent_tool_spec.get("coded_tool_url")
        if not url or not isinstance(url, str):
            raise ValueError(
                "RemoteToolActivation requires a non-empty 'coded_tool_url' in the agent spec"
            )
        self.url: str = url
        self.timeout_seconds: float = float(
            agent_tool_spec.get("remote_tool_timeout_seconds", DEFAULT_REMOTE_TOOL_TIMEOUT_SECONDS)
        )

    def get_name(self) -> str:
        """Return the agent's own name (for journal/origin tracking)."""
        name = self.agent_tool_spec.get("name")
        if isinstance(name, str) and name:
            return name
        return self.url

    async def build(self) -> BaseMessage:
        """
        Main entry point. POSTs (args, sly_data_redacted) to the origin's
        tool endpoint, applies from_downstream redaction to any sly_data the
        server returned, and returns an AIMessage with the tool output as
        content.
        """
        # Report tool start to the journal (LLM-visible structure).
        await self.journal.write_message(
            AgentMessage(
                content="Received arguments:",
                structure={"tool_start": True, "tool_args": self.arguments},
            )
        )

        # Apply sly_data redaction on the way out.
        outgoing_sly = self._redact_outgoing(self.sly_data)

        payload: Dict[str, Any] = {
            "args": self.arguments,
            "sly_data": outgoing_sly or {},
        }

        tool_error: bool = False
        tool_output: Any = None
        returned_sly: Dict[str, Any] = {}
        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    self.url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as response:
                    if response.status != 200:
                        body = await response.text()
                        tool_error = True
                        tool_output = (
                            f"Error: remote tool {self.url} returned HTTP "
                            f"{response.status}: {body[:300]}"
                        )
                    else:
                        result = await response.json()
                        tool_output = result.get("tool_output")
                        returned_sly = result.get("sly_data") or {}
                        if result.get("tool_error"):
                            tool_error = True
        except aiohttp.ClientError as exc:
            tool_error = True
            tool_output = (
                f"Error: remote tool {self.url} was unreachable: {exc}. "
                f"Cannot rely on results from it as a tool."
            )
            self.logger.warning("RemoteToolActivation network error %s: %s", self.url, exc)
        except json.JSONDecodeError as exc:
            tool_error = True
            tool_output = (
                f"Error: remote tool {self.url} returned non-JSON body: {exc}"
            )
        # pylint: disable=broad-exception-caught
        except Exception as exc:
            tool_error = True
            tool_output = f"Error: remote tool {self.url} failed: {exc}"
            self.logger.exception("RemoteToolActivation unexpected error")

        # Apply sly_data redaction on the way back in.
        if returned_sly:
            redacted_back = self._redact_incoming(returned_sly)
            # The new sly_data becomes the active sly_data for this activation;
            # higher-level wiring (LangChainRunContext) merges it into the shared
            # invocation context.
            self.sly_data = redacted_back

        # Report tool end to the journal.
        await self.journal.write_message(
            AgentMessage(
                content="Got result:",
                structure={
                    "tool_end": True,
                    "tool_error": tool_error,
                    "tool_output": tool_output,
                },
            )
        )

        return AIMessage(content=f"{tool_output}" if tool_output is not None else "")

    # ---- redaction helpers --------------------------------------------------

    def _redact_outgoing(self, sly_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Apply `allow.to_downstream.sly_data` from the agent spec."""
        if not sly_data:
            return {}
        redactor = SlyDataRedactor(
            self.agent_tool_spec,
            config_keys=["allow.to_downstream.sly_data"],
            allow_empty_dict=True,
        )
        return redactor.filter_config(sly_data) or {}

    def _redact_incoming(self, sly_data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply `allow.from_downstream.sly_data` from the agent spec."""
        redactor = SlyDataRedactor(
            self.agent_tool_spec,
            config_keys=["allow.from_downstream.sly_data"],
            allow_empty_dict=True,
        )
        return redactor.filter_config(sly_data) or {}

    async def close_of_work(self, parent_resource: RunContext = None):
        """Release resources owned by this context when the work is all done."""
        await super().close_of_work(parent_resource)
