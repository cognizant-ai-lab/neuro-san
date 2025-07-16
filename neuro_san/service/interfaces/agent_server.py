
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


class AgentServer:
    """
    Interface for an AgentServer, regardless of transport mechanism
    """

    # A space-delimited list of http metadata request keys to forward to logs/other requests
    DEFAULT_FORWARDED_REQUEST_METADATA: str = "request_id user_id"

    def stop(self):
        """
        Stop the server.
        """
        raise NotImplementedError
