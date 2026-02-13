
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

from neuro_san.interfaces.agent_session_constants import AgentSessionConstants


class AbstractHttpServiceAgentSession(AgentSessionConstants):
    """
    Abstract base class for sync and async version for http service agent sessions.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self, host: str = None,
                 port: str = None,
                 timeout_in_seconds: int = 30,
                 metadata: Dict[str, str] = None,
                 security_cfg: Dict[str, Any] = None,
                 umbrella_timeout: Timeout = None,
                 streaming_timeout_in_seconds: int = None,
                 agent_name: str = None):
        """
        Creates a AsyncAgentSession that asynchronously connects to the
        Agent Service and delegates its implementations to the service.

        :param host: the service host to connect to
                        If None, will use a default
        :param port: the service port
                        If None, will use a default
        :param timeout_in_seconds: timeout to use when communicating
                        with the service
        :param metadata: A grpc metadata of key/value pairs to be inserted into
                         the header. Default is None. Preferred format is a
                         dictionary of string keys to string values.
        :param security_cfg: An optional dictionary of parameters used to
                        secure the TLS and the authentication of the gRPC
                        connection.  Supplying this implies use of a secure
                        GRPC Channel.  Default is None, uses insecure channel.
        :param umbrella_timeout: A Timeout object under which the length of all
                        looping and retries should be considered
        :param streaming_timeout_in_seconds: timeout to use when streaming to/from
                        the service. Default is None, indicating connection should
                        stay open until the (last) result is yielded.
        :param agent_name: The name of the agent to talk to
        """
        _ = umbrella_timeout

        self.security_cfg: Dict[str, Any] = security_cfg
        self.use_host: str = "localhost"
        if host is not None:
            self.use_host = host

        self.use_port: str = str(self.DEFAULT_HTTP_PORT)
        if port is not None:
            self.use_port = port

        self.agent_name: str = agent_name

        self.timeout_in_seconds: int = timeout_in_seconds
        self.streaming_timeout_in_seconds: int = streaming_timeout_in_seconds
        self.metadata: Dict[str, str] = metadata

    def get_request_path(self, method: str) -> str:
        """
        :param method: The method endpoint we wish to reach
        :return: The full URL for accessing the method, given the host, port and agent_name.
        """
        scheme: str = "http"
        if self.security_cfg is not None:
            scheme = "https"

        if self.agent_name is None:
            return f"{scheme}://{self.use_host}:{self.use_port}/api/v1/{method}"
        return f"{scheme}://{self.use_host}:{self.use_port}/api/v1/{self.agent_name}/{method}"

    def get_headers(self) -> Dict[str, Any]:
        """
        Get headers for any outgoing request
        """
        headers: Dict[str, Any] = self.metadata
        if headers is None:
            headers = {}
        return headers

    def help_message(self, path: str) -> str:
        """
        Method returning general help message for http connectivity problems.
        :param path: url path of a request
        :return: help message
        """
        message = f"""
        Some basic suggestions to help debug connectivity issues:
        1. Ensure the server is running and reachable:
           ping <server_address>
           curl -v <server_url>
        2. Check network issues:
           traceroute <server_address>  # Linux/macOS
           tracert <server_address>  # Windows
        3. Ensure you are using correct protocol (http/https) and port number;
        4. Run service health check:
           curl <server_url:server_port>
        5. Try testing with increased timeout;
        6. Did you misspell the agent and/or method name in your {path} request path?
        7. If working with a local docker container:
           7.1 Does your http port EXPOSEd in the Dockerfile match your value for AGENT_HTTP_PORT?
           7.2 Did you add a -p <server_port>:<server_port> to your docker run command line to map container port(s)
               to your local ones?
        8. Is the agent turned on in your manifest.hocon?
        9. If you are attempting to use https, know that the default server configurations do not
           provide any of the necessary certificates for this to work and any certs used will
           need to be well known.  If you're unfamiliar with this process, it's a big deal.
           Try regular http instead.
        10. Is the server your are attempting to reach running with an AGENT_AUTHORIZER?
            If so, have the administrator for the server check its authorization
            policy/database to be sure the your user has the correct permissions for the network.
        """
        return message
