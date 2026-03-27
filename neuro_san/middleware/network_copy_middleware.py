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

import json
from logging import getLogger
from logging import Logger
from typing import Any
from typing import Dict
from typing_extensions import override

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware import AgentState
from langchain_core.messages import AIMessage

from neuro_san import REGISTRIES_DIR
from neuro_san.interfaces.reservation import Reservation
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
    ) -> dict[str, Any] | None:
        """
        Copy the agent network provided by the model's response.

        :param state: Current agent state
        :param runtime: Runtime context
        :return: Dict with error message and jump directive, or None if valid
        """
        response: str = state.get("messages")[-1].content
        args: Dict[str, str] = json.loads(response)

        copy_agent: str = args.get("agent_name")
        if copy_agent is None or len(copy_agent) == 0:
            return "Need a non-empty value for copy_agent"

        # Make sure we have a hocon file reference
        if not copy_agent.endswith(".hocon"):
            copy_agent = f"{copy_agent}.hocon"

        # Remove the .hocon suffix for this string
        use_agent_name: str = copy_agent[:-6]

        # Restore the given agent network to find its spec dictionary
        copy_file: str = REGISTRIES_DIR.get_file_in_basis(copy_agent)
        restorer = AgentNetworkRestorer()
        network: AgentNetwork = restorer.restore(file_reference=copy_file)
        my_agent_spec: Dict[str, Any] = network.get_config()

        # Creating Reservations can be done outside the with-statement
        lifetime_in_seconds: float = 5 * 60.0

        self.logger.info("Creating temporary network from %s", use_agent_name)
        reservation: Reservation = None
        error: str = None
        reservation, error = await ReservationUtil.wait_for_one(
            {"reservationist": self.reservationist},
            my_agent_spec,
            lifetime_in_seconds,
            prefix=f"copy_cat-{use_agent_name}"
        )

        if error is not None:
            self.logger.error("Error: %s", error)
            return error

        # Get info from the reservation
        reservation_id: str = reservation.get_reservation_id()
        lifetime_in_seconds: float = reservation.get_lifetime_in_seconds()
        self.logger.info("Successfully create tempory network %s", reservation_id)

        # Put the output in sly_data for less LLM "telephone" interference
        self.sly_data["agent_reservations"] = [
            {
                "reservation_id": reservation_id,
                "lifetime_in_seconds": lifetime_in_seconds,
                "expiration_time_in_seconds": reservation.get_expiration_time_in_seconds()
            }
        ]

        # Return message to provide the agent name and lifetime
        return {
            "messages": [
                AIMessage(
                    f"The temporary agent name is {reservation_id}. "
                    f"Hurry, it's only available for {lifetime_in_seconds} seconds."
                )
            ]
        }
