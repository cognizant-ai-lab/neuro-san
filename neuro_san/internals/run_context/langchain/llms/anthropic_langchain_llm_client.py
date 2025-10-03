
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

from contextlib import suppress

from neuro_san.internals.run_context.langchain.llms.langchain_llm_client import LangChainLlmClient


class AnthropicLangChainLlmClient(LangChainLlmClient):
    """
    Implementation of the LangChainLlmClient for Anthtropic chat models.

    Anthropic chat models do not allow for passing in an externally managed
    async web client.
    """

    async def delete_resources(self):
        """
        Release the run-time resources used by the model
        """
        if self.llm is None:
            return

        # Do the necessary reach-ins to successfully shut down the web client

        # This is really an anthropic.AsyncClient, but we don't really want to do the Resolver here.
        # Note we don't want to do this in the constructor, as AnthropicChat lazily
        # creates these as needed via a cached_property that needs to be done in its own time
        # via Anthropic infrastructure.  By the time we get here, it's already been created.
        anthropic_async_client: Any = self.llm._async_client     # pylint:disable=protected-access

        if anthropic_async_client is not None:
            with suppress(Exception):
                await anthropic_async_client.aclose()

        # Let's not do this again, shall we?
        self.llm = None
