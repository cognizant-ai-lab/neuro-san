
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

from neuro_san.internals.run_context.langchain.llms.langchain_llm_client import LangChainLlmClient


class BedrockLangChainLlmClient(LangChainLlmClient):
    """
    LangChainLlmClient implementation for Bedrock.

    Bedrock does not allow for passing in async web clients.
    As a matter of fact, all of its clients are synchronous,
    which is not the best for an async service.
    """

    async def delete_resources(self):
        """
        Release the run-time resources used by the model
        """
        if self.llm is None:
            return

        # Do the necessary reach-ins to successfully shut down the web client
        if self.llm.client is not None:
            # This is a boto3 client
            self.llm.client.close()

        if self.llm.bedrock_client is not None:
            # This is a boto3 client
            self.llm.bedrock_client.close()

        # Let's not do this again, shall we?
        self.llm = None
