
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

import ast
import re
from re import Match
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import TypeVar

from pydantic import ConfigDict

from langchain.agents.output_parsers.tools import ToolsAgentOutputParser
from langchain_core.outputs import Generation

from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.messages.agent_message import AgentMessage

# Bizarre convention from the superclass to adhere to overridden method.
T = TypeVar("T")


class JournalingToolsAgentOutputParser(ToolsAgentOutputParser):
    """
    ToolsAgentOutputParser implementation that intercepts agent-level chatter

    We use this to intercept the "Invoking <agent> with <params>" kinds of messages
    to stream them back to the client as AgentMessages.
    """

    # Declarations of member variables here satisfy Pydantic style,
    # which is a type validator that langchain is based on which
    # is able to use JSON schema definitions to validate fields.
    journal: Journal

    # This guy needs to be a pydantic class and in order to have
    # a non-pydantic Journal as a member, we need to do this.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, journal: Journal):
        """
        Constructor

        :param journal: The journal to write messages to
        """
        super().__init__(journal=journal)

    async def aparse_result(self, result: list[Generation], *, partial: bool = False) -> T:
        """
        Comments and method signature from superclass method.
        Async parse a list of candidate model Generations into a specific format.

        The return value is parsed from only the first Generation in the result, which
            is assumed to be the highest-likelihood Generation.

        Args:
            result: A list of Generations to be parsed. The Generations are assumed
                to be different candidate outputs for a single model input.
            partial: Whether to parse the output as a partial result. This is useful
                for parsers that can parse partial results. Default is False.

        Returns:
            Structured output.
        """
        # Do the superclass thing
        result = await super().aparse_result(result, partial=partial)

        # By empirical observation, when the result is a list, we are getting
        # the "Invoking" message, which is useful when wanting to know agent thoughts.
        # There is one AgentAction instance in the list per tool invocation,
        # and that guy's log member has the message we want to stream as
        # agent thought..
        if isinstance(result, List):
            for action in result:
                if action.log is not None and len(action.log) > 0:
                    agent_name, params_str = self._extract_agent_and_params(action.log)
                    params: Dict[str, Any] = ast.literal_eval(params_str)
                    action_dict: Dict[str, Any] = {
                        "invokingStart": True,
                        "invoked_agent_name": agent_name,
                        "params": params
                    }
                    message = AgentMessage(content=action.log.strip(), structure=action_dict)
                    await self.journal.write_message(message)

        # Note: We do not care about AgentFinish
        return result

    def _extract_agent_and_params(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Extracts the agent name and parameters string from a sentence formatted as:
        "Invoking `<agent_name>` with `<params>`".

        :param text: Input text in the format "Invoking agent_name with params".

        :return: A tuple of (agent_name, params) if matched; otherwise (None, None).
        """
        match: Match = re.search(r"Invoking:\s+`(.*)`\s+with\s+`(.*)`", text)
        if match:
            agent, params = match.groups()
            return agent.strip(), params.strip()
        return None, None
