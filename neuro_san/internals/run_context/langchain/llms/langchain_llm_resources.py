
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

from langchain_core.language_models.base import BaseLanguageModel

from neuro_san.internals.run_context.langchain.llms.client_policy import ClientPolicy


class LangChainLlmResources:
    """
    Class for representing a LangChain model
    together with run-time policy necessary for model usage by the service.
    """

    def __init__(self, model: BaseLanguageModel, client_policy: ClientPolicy = None):
        """
        Constructor.
        :param model: Language model used.
        :param client_policy: optional ClientPolicy object to manage connections to LLM host.
        """
        self.model: BaseLanguageModel = model
        self.client_policy: ClientPolicy = client_policy

    def get_model(self) -> BaseLanguageModel:
        """
        :return: the BaseLanguageModel
        """
        return self.model

    def get_client_policy(self) -> ClientPolicy:
        """
        :return: the ClientPolicy used by the model
        """
        return self.client_policy

    async def delete_resources(self):
        """
        Release the run-time resources used by the model
        """
        if self.client_policy is not None:
            await self.client_policy.delete_resources()
