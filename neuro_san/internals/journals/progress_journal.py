
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

from neuro_san.interfaces.agent_progress_reporter import AgentProgressReporter
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.messages.agent_progress_message import AgentProgressMessage


class ProgressJournal(AgentProgressReporter):
    """
    An implementation of the AgentProgressReporter interface for a CodedTool to be able
    to journal AgentProgressMessages.
    """

    def __init__(self, wrapped_journal: Journal):
        """
        Constructor

        :param wrapped_journal: The Journal that this implementation wraps
        """
        self.wrapped_journal: Journal = wrapped_journal

    async def async_report_progress(self, structure: Dict[str, Any], content: str = ""):
        """
        Reports the structure and optional message to the chat message stream returned to the client
        To be used from within CodedTool.async_invoke().

        :param structure: The Dictionary instance to write as progress.
                        All keys and values must be JSON-serializable.
        :param content: An optional message to send to the client
        """
        if structure is None:
            # Nothing to report
            return
        if not isinstance(structure, Dict):
            raise ValueError(f"Expected dictionary, got {type(structure)}")

        if content is None:
            content = ""

        message = AgentProgressMessage(content, structure=structure)
        await self.wrapped_journal.write_message(message)
