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

from json import JSONDecodeError
from json import loads
from logging import getLogger
from logging import Logger
from typing import Any
from typing import Dict
from typing_extensions import override

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware import AgentState
from langchain_core.messages import AIMessage

from neuro_san import REGISTRIES_DIR
from neuro_san.interfaces.reservationist import Reservationist
from neuro_san.internals.graph.persistence.agent_network_restorer import AgentNetworkRestorer
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.reservations.reservation_util import ReservationUtil


class NetworkCopyMiddleware(AgentMiddleware):
    """
    Middleware that copies an existing agent network into a temporary reservation.

    After the agent responds, this middleware parses the model's output as a JSON
    object with an "agent_name" key, loads the corresponding .hocon network spec,
    and creates a time-limited reservation for it via the Reservationist interface.
    The reservation details are stored in sly_data for downstream consumers.

    Note: The copied network is not currently invoked from within the middleware.
    Doing so is possible but would require passing the invocation context to the
    middleware and performing a dynamic tool call. This may be added in a future
    iteration. For now, this serves as a proof of concept for using the Reservations
    infrastructure in middleware.
    """

    def __init__(self, reservationist: Reservationist, sly_data: Dict[str, Any]) -> None:
        """
        Initialize the middleware.
        :param reservationist: Reservationist implementation that allows procurement of agent ids
                for a specific amount of time for direct sessions only.
        :param sly_data: A dictionary whose keys are defined by the agent hierarchy,
                but whose values are meant to be kept out of the chat stream.

                This dictionary is largely to be treated as read-only.
                It is possible to add key/value pairs to this dict that do not
                yet exist as a bulletin board, as long as the responsibility
                for which coded_tool publishes new entries is well understood
                by the agent chain implementation and the coded_tool implementation
                adding the data is not invoke()-ed more than once.
        """
        self.reservationist = reservationist
        self.sly_data = sly_data
        self.logger: Logger = getLogger(self.__class__.__name__)

    @override
    async def aafter_agent(
        self,
        state: AgentState,
        runtime: Any
    ) -> Dict[str, Any] | None:
        """
        Copy the agent network provided by the model's response.

        :param state: Current agent state
        :param runtime: Runtime context
        :return: Dict with error message and jump directive, or None if valid
        """
        response: str = state.get("messages")[-1].content

        agent_name: str = self._parse_agent_name(response)
        if agent_name is None:
            return self._agent_response("Please provide the name of the network to copy.")

        network: AgentNetwork = self._restore_network(agent_name)
        if not network:
            self.logger.error("Cannot find agent %s", agent_name)
            return self._agent_response(
                f"Cannot find agent {agent_name}. "
                "Please provide a valid name of the network to copy."
            )

        lifetime_in_seconds: float = 5 * 60.0
        self.logger.info("Creating temporary network from %s", agent_name)
        reservation, error = await ReservationUtil.wait_for_one(
            {"reservationist": self.reservationist},
            network.get_config(),
            lifetime_in_seconds,
            prefix=f"copy_cat-{agent_name}"
        )

        if error is not None:
            self.logger.error("Error: %s", error)
            return self._agent_response(f"Got the following error: {error}.")

        reservation_id: str = reservation.get_reservation_id()
        lifetime_in_seconds = reservation.get_lifetime_in_seconds()
        self.logger.info("Successfully created temporary network %s", reservation_id)

        self.sly_data["agent_reservations"] = [
            {
                "reservation_id": reservation_id,
                "lifetime_in_seconds": lifetime_in_seconds,
                "expiration_time_in_seconds": reservation.get_expiration_time_in_seconds()
            }
        ]

        return self._agent_response(
            f"The temporary agent name is {reservation_id}. "
            f"Hurry, it's only available for {lifetime_in_seconds} seconds."
        )

    def _agent_response(self, message: str) -> Dict[str, Any]:
        """Return an agent response dict with the given message."""
        return {"messages": [AIMessage(message)]}

    def _parse_agent_name(self, response: str) -> str | None:
        """
        Parse the model response JSON and extract the agent name.

        :param response: Raw model response string
        :return: The agent name, or None if parsing/validation fails
        """
        try:
            args: Dict[str, str] = loads(response)
        except JSONDecodeError as json_error:
            self.logger.error("Cannot parse '%s' into JSON format. Got %s", response, json_error)
            return None

        agent_name: str = args.get("agent_name")
        if not agent_name or not isinstance(agent_name, str):
            self.logger.error("Need a non-empty string for agent name")
            return None

        if agent_name.endswith(".hocon"):
            agent_name = agent_name[:-6]

        return agent_name

    def _restore_network(self, agent_name: str) -> AgentNetwork | None:
        """
        Restore an agent network from the registry by name.

        :param agent_name: Agent name (with or without .hocon suffix)
        :return: The restored AgentNetwork, or None if not found
        """
        hocon_name: str = f"{agent_name}.hocon"
        copy_file: str = REGISTRIES_DIR.get_file_in_basis(hocon_name)
        restorer = AgentNetworkRestorer()
        return restorer.restore(file_reference=copy_file)
