
# Copyright © 2023-2026 Cognizant Technology Solutions Corp, www.cognizant.com.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# END COPYRIGHT
from typing import Any
from typing import Dict

from neuro_san.interfaces.agent_progress_reporter import AgentProgressReporter
from neuro_san.internals.journals.journal import Journal
from neuro_san.message.utils.agent_progress_message import AgentProgressMessage


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
