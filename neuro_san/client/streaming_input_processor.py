
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
from typing import Generator
from typing import Optional

from copy import copy

from neuro_san.client.thinking_file_message_processor import ThinkingFileMessageProcessor
from neuro_san.interfaces.agent_session import AgentSession
from neuro_san.internals.messages.chat_message_type import ChatMessageType
from neuro_san.internals.messages.origination import Origination
from neuro_san.message_processing.basic_message_processor import BasicMessageProcessor
from neuro_san.session.direct_agent_session import DirectAgentSession


class StreamingInputProcessor:
    """
    Processes AgentCli input by using the neuro-san streaming API.
    """

    def __init__(self,
                 default_input: str = "",
                 thinking_file: str = None,
                 session: AgentSession = None,
                 thinking_dir: str = None):
        """
        Constructor
        """
        super().__init__()
        self.default_input: str = default_input
        self.session: AgentSession = session
        self.processor = BasicMessageProcessor()
        if thinking_dir is not None and thinking_file is not None:
            self.processor.add_processor(ThinkingFileMessageProcessor(thinking_file, thinking_dir))

        if self.session is None:
            raise ValueError("StreamingInputProcessor session cannot be None")

    def get_message_processor(self) -> BasicMessageProcessor:
        """
        :return: The message processor
        """
        return self.processor

    # pylint: disable=too-many-locals
    def process_once(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Use polling strategy to communicate with agent.
        :param state: The state dictionary to pass around
        :return: An updated state dictionary
        """
        empty: Dict[str, Any] = {}
        user_input: str = state.get("user_input")
        last_chat_response = state.get("last_chat_response")
        num_input = state.get("num_input")
        chat_context = state.get("chat_context", empty)
        chat_filter = state.get("chat_filter", empty)
        origin_str: str = ""

        if user_input is None or user_input == self.default_input:
            return state

        sly_data: Optional[Dict[str, Any]] = state.get("sly_data", None)
        # Note that by design, a client does not have to interpret the
        # chat_context at all. It merely needs to pass it along to continue
        # the conversation.
        chat_request: Dict[str, Any] = self.formulate_chat_request(user_input, sly_data,
                                                                   chat_context, chat_filter)
        self.reset()

        return_state: Dict[str, Any] = copy(state)
        returned_sly_data: Optional[Dict[str, Any]] = None
        chat_responses: Generator[Dict[str, Any], None, None] = self.session.streaming_chat(chat_request)
        for chat_response in chat_responses:

            response: Dict[str, Any] = chat_response.get("response", empty)

            self.processor.process_message(response)

            # Update the state if there is something to update it with
            chat_context = self.processor.get_chat_context()
            last_chat_response = self.processor.get_compiled_answer()
            returned_sly_data: Dict[str, Any] = self.processor.get_sly_data()
            origin_str = Origination.get_full_name_from_origin(self.processor.get_answer_origin())

        # Update the sly_data if new sly_data was returned
        if returned_sly_data is not None:
            if sly_data is not None:
                sly_data.update(returned_sly_data)
            else:
                sly_data = returned_sly_data.copy()

        if origin_str is None or len(origin_str) == 0:
            origin_str = "agent network"

        update = {
            "chat_context": chat_context,
            "num_input": num_input + 1,
            "last_chat_response": last_chat_response,
            "user_input": None,
            "sly_data": sly_data,
            "origin_str": origin_str
        }
        return_state.update(update)

        return return_state

    def formulate_chat_request(self, user_input: str,
                               sly_data: Dict[str, Any] = None,
                               chat_context: Dict[str, Any] = None,
                               chat_filter: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Formulates a single chat request given the user_input
        :param user_input: The string to send
        :param sly_data: The sly_data dictionary to send
        :param chat_context: The chat context dictionary that allows the context of a
                    continuing conversation to be reconstructed on another server.
        :param chat_filter: The ChatFilter to apply to the request.
        :return: A dictionary representing the chat request to send
        """
        chat_request = {
            "user_message": {
                "type": ChatMessageType.HUMAN,
                "text": user_input
            }
        }

        if bool(chat_context):
            # Recall that non-empty dictionaries evaluate to True
            chat_request["chat_context"] = chat_context

        if sly_data is not None and len(sly_data.keys()) > 0:
            chat_request["sly_data"] = sly_data

        if chat_filter is not None and len(chat_filter.keys()) > 0:
            chat_request["chat_filter"] = chat_filter

        return chat_request

    def reset(self):
        """
        Reset for a new exchange
        """
        # Reset the message processor to receive a new answer
        self.processor.reset()

        if isinstance(self.session, DirectAgentSession):
            # Direct sessions need their Origination reset otherwise chat_context
            # origins do not match up.
            self.session.reset()
