
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
from typing import List

from neuro_san.internals.run_context.interfaces.run_context import RunContext


class CallableActivation:
    """
    Interface describing what a CallingActivation can access
    when invoking LLM function calls.
    """

    async def build(self) -> str:
        """
        Main entry point to the class.

        :return: A string representing a List of messages produced during this process.
        """
        raise NotImplementedError

    def get_origin(self) -> List[Dict[str, Any]]:
        """
        :return: A List of origin dictionaries indicating the origin of the tool.
                The origin can be considered a path to the original call to the front-man.
                Origin dictionaries themselves each have the following keys:
                    "tool"                  The string name of the tool in the spec
                    "instantiation_index"   An integer indicating which incarnation
                                            of the tool is being dealt with.
        """
        raise NotImplementedError

    async def delete_resources(self, parent_run_context: RunContext):
        """
        Cleans up after any allocated resources on their server side.
        :param parent_run_context: The RunContext which contains the scope
                    of operation of this CallableNode
        """
        raise NotImplementedError
