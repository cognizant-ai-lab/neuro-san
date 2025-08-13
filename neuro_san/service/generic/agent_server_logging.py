
# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT

from typing import Dict
from typing import List

import logging
import os

from leaf_server_common.logging.logging_setup import setup_logging
from leaf_server_common.server.grpc_metadata_forwarder import GrpcMetadataForwarder

from neuro_san.internals.utils.file_of_class import FileOfClass


class AgentServerLogging:
    """
    Common logging setup for the agent server threads.
    """

    def __init__(self, server_name_for_logs: str,
                 forwarded_request_metadata_str: str):
        """
        Constructor

        :param server_name_for_logs: The server name (source) to be used in structured logging messages
        :param forwarded_request_metadata_str: A space-delimited string of http header metadata
                            whose key/value pairs are to be forwarded on to the logging system.
                            Note that individual keys must be snake_case. No capitals.
                            (I guess per HTTP rules).
        """
        self.server_name_for_logs: str = server_name_for_logs
        self.forwarded_request_metadata: List[str] = forwarded_request_metadata_str.split(" ")

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

        # Make for easy running from the neuro-san repo
        if os.environ.get("AGENT_SERVICE_LOG_JSON") is None:
            # Use the log file that is local to the repo
            file_of_class = FileOfClass(__file__, path_to_basis="../../deploy")
            os.environ["AGENT_SERVICE_LOG_JSON"] = file_of_class.get_file_in_basis("logging.json")

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
        setup_logging(self.server_name_for_logs, current_dir,
                      'AGENT_SERVICE_LOG_JSON',
                      'AGENT_SERVICE_LOG_LEVEL',
                      extra_logging_defaults)

        # This module within openai library can be quite chatty w/rt http requests
        logging.getLogger("httpx").setLevel(logging.WARNING)
