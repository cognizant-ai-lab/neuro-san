
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

from neuro_san.client.agent_session_factory import AgentSessionFactory
from neuro_san.client.streaming_input_processor import StreamingInputProcessor
from neuro_san.interfaces.agent_session import AgentSession
from neuro_san.message.processors.basic_message_processor import BasicMessageProcessor


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
        self.processor: BasicMessageProcessor = None

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
        self.processor = input_processor.get_message_processor()
        request: Dict[str, Any] = input_processor.formulate_chat_request(text)

        # Call streaming_chat()
        empty: Dict[str, Any] = {}
        for chat_response in session.streaming_chat(request):
            message: Dict[str, Any] = chat_response.get("response", empty)
            self.processor.process_message(message, chat_response.get("type"))

        raw_answer: str = self.processor.get_compiled_answer()

        return raw_answer

    def get_processor(self) -> BasicMessageProcessor:
        """
        :return: The message processor holding the details of the answer from the agent
        """
        return self.processor
