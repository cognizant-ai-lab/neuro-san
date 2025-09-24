
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


class AgentProgressReporter:
    """
    An interface for CodedTools to be able to report on an agent network's progress.

    Instances get handed down via the CodedTool's arguments dictionary via the
    "progress_reporter" key via the invoke() or async_invoke() methods.

    Typically, progress is reported as a dictionary that is JSON-serializable
    and interpreted by the client on a per-agent-network basis in the structure.
    The simplest and most easily interpreted structure is simply to report a key of "progress"
    with a value of a float between 0.0 and 1.0, but other keys/values can be used to report
    (say) partial progress on a structure that is being built by the agent network so that it
    can be visualized by an in-the-know client.

    Text messages can also be sent as content, but more as differential comments.
    These are not recommended, as any given client may not be able to parse them very easily.
    """

    async def async_report_progress(self, structure: Dict[str, Any], content: str = ""):
        """
        Reports the structure and optional message to the chat message stream returned to the client
        To be used from within CodedTool.async_invoke().

        :param structure: The Dictionary instance to write as progress.
                        All keys and values must be JSON-serializable.
        :param content: An optional message to send to the client
        """
        raise NotImplementedError
