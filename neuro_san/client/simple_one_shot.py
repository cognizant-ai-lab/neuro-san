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

import json

from neuro_san.client.agent_session_factory import AgentSessionFactory
from neuro_san.client.streaming_input_processor import StreamingInputProcessor
from neuro_san.interfaces.agent_session import AgentSession
from neuro_san.message_processing.basic_message_processor import BasicMessageProcessor


class SimpleOneShot:
    """
    Encapulates basic operation of sending a single message to an agent
    and getting single aswer back.
    """

    def __init__(self, agent: str, connection_type: str = "direct",
                 host: str = None, port: int = None):
        """
        Constructor

        :param agent: The name of the agent to talk to
        :param connection_type: The string type of connection.
                    Can be http, grpc, or direct (for library usage).
                    Default is direct.
        :param hostname: The name of the host to connect to (if applicable)
        :param port: The port on the host to connect to (if applicable)
        """
        self.agent: str = agent
        self.connection_type: str = connection_type
        self.host: str = host
        self.port: int = port

    def get_answer_for(self, text: str) -> str:
        """
        Sends text to the agent and returns the agent's answer
        :param text: The text to send to the agent
        :return: The text answer from the agent.
        """
        session: AgentSession = AgentSessionFactory().create_session(self.connection_type,
                                                                     self.agent,
                                                                     hostname=self.host,
                                                                     port=self.port)
        input_processor = StreamingInputProcessor(session=session)
        processor: BasicMessageProcessor = input_processor.get_message_processor()
        request: Dict[str, Any] = input_processor.formulate_chat_request(text)

        # Call streaming_chat()
        empty: Dict[str, Any] = {}
        for chat_response in session.streaming_chat(request):
            message: Dict[str, Any] = chat_response.get("response", empty)
            processor.process_message(message, chat_response.get("type"))

        raw_answer: str = processor.get_answer()
        structure: Dict[str, Any] = processor.get_structure()
        if structure is not None:
            raw_answer += "\n```json" + json.dumps(structure, indent=4, sort_keys=True) + "```"

        return raw_answer
