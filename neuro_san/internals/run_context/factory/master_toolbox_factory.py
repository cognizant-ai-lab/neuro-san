
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
from typing import Dict

from neuro_san.internals.interfaces.context_type_toolbox_factory import ContextTypeToolboxFactory
from neuro_san.internals.run_context.factory.master_llm_factory import MasterLlmFactory
from neuro_san.internals.run_context.langchain.toolbox.toolbox_factory import ToolboxFactory


class MasterToolboxFactory:
    """
    Creates the correct kind of ContextTypeToolboxFactory
    """

    @staticmethod
    def create_toolbox_factory(config: Dict[str, Any] = None) -> ContextTypeToolboxFactory:
        """
        Creates an appropriate ContextTypeToolboxFactory

        :param config: The config dictionary which may or may not contain
                       keys for the context_type and default toolbox_config
        :return: A ContextTypeToolboxFactory appropriate for the context_type in the config.
        """

        toolbox_factory: ContextTypeToolboxFactory = None
        context_type: str = MasterLlmFactory.get_context_type(config)

        if context_type.startswith("openai"):
            toolbox_factory = None
        elif context_type.startswith("langchain"):
            toolbox_factory = ToolboxFactory(config)
        else:
            # Default case
            toolbox_factory = ToolboxFactory(config)

        return toolbox_factory
