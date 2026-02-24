
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

import logging
import os

from leaf_server_common.logging.logging_setup import setup_logging
from leaf_server_common.server.grpc_metadata_forwarder import GrpcMetadataForwarder


class AgentServerLogging:
    """
    Common logging setup for the agent server threads.
    """

    def __init__(self, server_name_for_logs: str,
                 forwarded_request_metadata_str: str,
                 logging_config: Dict[str, Any] = None):
        """
        Constructor

        :param server_name_for_logs: The server name (source) to be used in structured logging messages
        :param forwarded_request_metadata_str: A space-delimited string of http header metadata
                            whose key/value pairs are to be forwarded on to the logging system.
                            Note that individual keys must be snake_case. No capitals.
                            (I guess per HTTP rules).
        :param logging_config: A dictionary of configuration parameters for the logging system
        """
        self.server_name_for_logs: str = server_name_for_logs
        self.forwarded_request_metadata: List[str] = forwarded_request_metadata_str.split(" ")
        self.logging_config: Dict[str, Any] = logging_config

    def get_forwarder(self) -> GrpcMetadataForwarder:
        """
        :return: A GrpcMetadataForwarder instance initialized with
                 the list of forwarded request metadata keys
        """
        return GrpcMetadataForwarder(self.forwarded_request_metadata)

    def setup_logging(self, metadata: Dict[str, str] = None, request_id: str = "None"):
        """
        Set up logging for agent server threads.

        :param metadata: An optional dictionary with actual metadata
        :param request_id: An optional request_id string.  Default is "None".
        """

        # Need to initialize the forwarded metadata default values before our first
        # call to a logger (which is below!).
        extra_logging_defaults: Dict[str, str] = {
            "source": self.server_name_for_logs,
            "user_id": "None",
            "request_id": request_id,
        }
        if len(self.forwarded_request_metadata) > 0:
            for key in self.forwarded_request_metadata:
                if metadata is not None:
                    extra_logging_defaults[key] = metadata.get(key, "None")
                else:
                    extra_logging_defaults[key] = "None"

        current_dir: str = os.path.dirname(os.path.abspath(__file__))
        setup_logging(self.server_name_for_logs,
                      default_log_dir=current_dir,
                      log_level_env="AGENT_SERVICE_LOG_LEVEL",
                      extra_logging_fields_defaults=extra_logging_defaults,
                      logging_config=self.logging_config)

        # This module within openai library can be quite chatty w/rt http requests
        logging.getLogger("httpx").setLevel(logging.WARNING)

    def redact_per_env_var(self, input_str: str, env_var_name: str) -> str:
        """
        Redact a string using the value of an environment variable.

        :param input_str: The string to redact
        :param env_var_name: The name of the environment variable
        :return: The redacted string
        """
        value: str = f"'{input_str}'"

        # Determine the value of the environment variable
        slice_str: str = os.environ.get(env_var_name)
        if slice_str is not None and len(slice_str) > 0:

            # Deterimine the extent and direction of the slice
            try:
                marker_slice: int = int(slice_str)

                if marker_slice == 0:
                    value = "<redacted>"
                elif marker_slice < 0:
                    one_slice: str = input_str[marker_slice:]
                    prefix: str = ""
                    if -marker_slice < len(input_str):
                        prefix = "..."
                    value = f"'{prefix}{one_slice}'"
                else:
                    one_slice: str = input_str[:marker_slice]
                    suffix: str = ""
                    if marker_slice < len(input_str):
                        suffix = "..."
                    value = f"'{one_slice}{suffix}'"
            except ValueError:
                # Not an int
                logging.getLogger(self.__class__.__name__).info(
                    "Value for %s: '%s' needs to be integer or empty string.",
                    env_var_name, slice_str)

        return value
