
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
Handler for the Agent Web GET /api/v1/{agent_name}/network endpoint.

Returns a Jupyter notebook (.ipynb) carrying the scrubbed wire form of the
agent network so a runtime ("browser") can fetch and execute it locally.

See docs/agent_web_design.md (§5.3).
"""
import json
import re
from http import HTTPStatus
from typing import Any
from typing import Dict

from neuro_san.internals.distribution.agent_web_notebook import build_agent_web_notebook
from neuro_san.internals.distribution.published_network_scrubber import PublishedNetworkScrubber
from neuro_san.internals.distribution.published_network_scrubber import PublishedScrubberError
from neuro_san.internals.graph.registry.activation_factory import ActivationFactory
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.storage_class import StorageClass
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.service.http.handlers.base_request_handler import BaseRequestHandler


# Agent network names must match this pattern. The URL route accepts any
# non-slash characters, so an attacker could otherwise smuggle quotes, CRLF,
# control bytes, or HTML/JS payloads into headers and response bodies. Names
# in neuro-san manifests have always been simple identifiers (the typical
# stem of a .hocon file), so this pattern matches every legitimate name.
# NB: `\Z` not `$` — in Python, `$` matches just before a trailing newline,
# so an attacker could pass "agent\n" through `.match()`. `\Z` matches only
# end-of-string and closes that header-injection path.
SAFE_AGENT_NAME_RE = re.compile(r"\A[A-Za-z0-9_\-]{1,128}\Z")


class NetworkHandler(BaseRequestHandler):
    """
    Handler class for the Agent Web /network endpoint.
    """

    async def get(self, agent_name: str):
        """
        Serve the scrubbed agent network as a Jupyter notebook.
        """
        # Reject any agent_name that doesn't match the safe identifier
        # pattern BEFORE we use it in any response header, body, or log line.
        # Tornado decodes URL-encoded path parameters, so an attacker can
        # otherwise inject CRLF, quotes, or HTML/JS payloads through here.
        if not SAFE_AGENT_NAME_RE.match(agent_name):
            self.set_status(HTTPStatus.BAD_REQUEST)
            self.set_header("Content-Type", "application/json")
            self.write({"error": "Invalid agent name."})
            self.do_finish()
            return

        metadata: Dict[str, Any] = self.get_metadata()

        # We do the request-rate accounting like the other handlers so that
        # the network endpoint is subject to the same global throttling.
        status_code, err_message = self.application.try_start_client_request(
            metadata, f"{agent_name}/network"
        )
        if status_code != HTTPStatus.OK:
            self.do_finish(status_code, err_message)
            return

        try:
            agent_network = self._lookup_network(agent_name)
            if agent_network is None:
                # Either the agent does not exist or it is not published.
                # We intentionally do not echo the user-supplied agent_name
                # back into the body; do_finish HTML-escapes it for us via
                # safe_message, but generic messages are still safer.
                self.do_finish(
                    HTTPStatus.NOT_FOUND,
                    "Agent network is not published on this server.",
                )
                return

            origin: str = self._derive_origin()
            factory = ActivationFactory(agent_network)
            scrubber = PublishedNetworkScrubber(
                agent_tool_path=factory.get_agent_tool_path()
            )
            try:
                wire = scrubber.scrub(agent_network, origin)
            except PublishedScrubberError as exc:
                self.logger.error(metadata, "Scrubber refused to publish %s: %s", agent_name, exc)
                self.do_finish(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    f"Network {agent_name!r} cannot be safely published: {exc}",
                )
                return

            notebook: Dict[str, Any] = build_agent_web_notebook(wire)

            # Agent Web is meant to be cross-origin friendly. Always emit CORS
            # headers on this endpoint so JupyterLite / browser runtimes can
            # fetch it from any host.
            self.set_header("Access-Control-Allow-Origin", "*")
            self.set_header("Content-Type", "application/x-ipynb+json")
            self.set_header(
                "Content-Disposition",
                f'inline; filename="{agent_name}.ipynb"',
            )
            self.write(json.dumps(notebook, indent=2))
        # pylint: disable=broad-exception-caught
        except Exception as exc:
            self.process_exception(exc)
        finally:
            self.do_finish()
            self.application.finish_client_request(metadata, f"{agent_name}/network")

    async def options(self, *_args, **_kwargs):
        """CORS preflight for the network endpoint."""
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type")
        self.set_status(HTTPStatus.NO_CONTENT)
        self.do_finish()

    def _lookup_network(self, agent_name: str) -> AgentNetwork:
        """Return the AgentNetwork iff it exists and is published."""
        network_storage_dict: Dict[str, AgentNetworkStorage] = (
            self.server_context.get_network_storage_dict()
        )
        public_storage: AgentNetworkStorage = network_storage_dict.get(StorageClass.PUBLIC)
        if public_storage is None:
            return None
        # We use the table directly because the provider abstraction does not
        # expose the AgentNetwork object back; the storage's internal map is
        # the right place to ask.
        # pylint: disable=protected-access
        agent_network: AgentNetwork = public_storage.agents_table.get(agent_name)
        if agent_network is None:
            return None
        if not agent_network.is_published():
            return None
        return agent_network

    def _derive_origin(self) -> str:
        """
        Determine the origin URL that the scrubber should stamp into the wire
        config. Uses request scheme/host with a fallback to an env-configured
        explicit origin (useful when the server sits behind a reverse proxy).
        """
        # Honor X-Forwarded-Proto / X-Forwarded-Host when set (reverse-proxy aware).
        scheme = self.request.headers.get("X-Forwarded-Proto") or self.request.protocol
        host = self.request.headers.get("X-Forwarded-Host") or self.request.host
        return f"{scheme}://{host}"
