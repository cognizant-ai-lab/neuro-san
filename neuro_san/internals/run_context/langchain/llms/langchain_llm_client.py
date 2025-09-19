
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
from typing import Any


class LangChainLlmClient:
    """
    Interface for representing a client that connects to a LangChain model
    """

    def get_client(self) -> Any:
        """
        Get the client used by the model
        """
        raise NotImplementedError

    async def delete_resources(self):
        """
        Release the run-time resources used by the model
        """
        raise NotImplementedError
