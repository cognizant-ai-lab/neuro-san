
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

from leaf_common.time.timeout import Timeout

from neuro_san.client.direct_agent_storage_util import DirectAgentStorageUtil
from neuro_san.interfaces.concierge_session import ConciergeSession
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.session.direct_concierge_session import DirectConciergeSession
from neuro_san.session.http_concierge_session import HttpConciergeSession


# pylint: disable=too-many-arguments,too-many-positional-arguments
class ConciergeSessionFactory:
    """
    Factory class for ConciregeSessions.
    """

    def create_session(self, session_type: str,
                       hostname: str = None,
                       port: int = None,
                       metadata: Dict[str, str] = None,
                       connect_timeout_in_seconds: float = None) -> ConciergeSession:
        """
        :param session_type: The type of session to create
        :param hostname: The name of the host to connect to (if applicable)
        :param port: The port on the host to connect to (if applicable)
        :param metadata: A metadata dictionary of key/value pairs to be inserted into
                         the header. Default is None. Preferred format is a
                         dictionary of string keys to string values.
        :param connect_timeout_in_seconds: A timeout in seconds after which attempts
                        to reach a server will stop. By default, this is None,
                        meaning sessions will try forever.
        """
        session: ConciergeSession = None

        umbrella_timeout: Timeout = None
        if connect_timeout_in_seconds is not None:
            umbrella_timeout = Timeout()
            umbrella_timeout.set_limit_in_seconds(connect_timeout_in_seconds)

        # Incorrectly flagged as destination of Trust Boundary Violation 1
        #   Reason: This is the place where the session_type enforced-string argument is
        #           actually checked for positive use.
        if session_type == "direct":
            # This only looks at public networks, which is what we want.
            network_storage: AgentNetworkStorage = DirectAgentStorageUtil.create_network_storage()
            session = DirectConciergeSession(network_storage, metadata=metadata)
        elif session_type in ("http", "https"):

            # If there is no port really specified, use the default port
            use_port = port
            if port is None:
                use_port = ConciergeSession.DEFAULT_PORT

            security_cfg: Dict[str, Any] = None
            if session_type == "https":
                # For now, to get the https scheme
                security_cfg = {}
            session = HttpConciergeSession(host=hostname, port=use_port,
                                           security_cfg=security_cfg, metadata=metadata,
                                           timeout_in_seconds=connect_timeout_in_seconds)
        else:
            # Incorrectly flagged as destination of Trust Boundary Violation 2
            #   Reason: This is the place where the session_type enforced-string argument is
            #           actually checked for negative use.
            raise ValueError(f"session_type {session_type} is not understood")

        return session
