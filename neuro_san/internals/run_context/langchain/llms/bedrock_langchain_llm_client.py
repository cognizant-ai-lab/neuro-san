
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

from neuro_san.internals.run_context.langchain.llms.langchain_llm_client import LangChainLlmClient


class BedrockLangChainLlmClient(LangChainLlmClient):
    """
    LangChainLlmClient implementation for Bedrock
    """

    def __init__(self, boto_client: Any, bedrock_client: Any):
        """
        Constructor

        :param boto_client: boto client
        :param bedrock_client: bedrock client
        """
        self.boto_client = boto_client
        self.bedrock_client = bedrock_client

    def get_client(self) -> Any:
        """
        Get the client used by the model
        """
        return self.boto_client

    async def delete_resources(self):
        """
        Release the run-time resources used by the model
        """
        # Neither of these clients are async.
        if self.boto_client is not None:
            self.boto_client.close()
            self.boto_client = None

        if self.bedrock_client is not None:
            self.bedrock_client.close()
            self.bedrock_client = None
