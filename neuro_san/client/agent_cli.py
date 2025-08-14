
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

import os
import shutil

import argparse
import json

from pathlib import Path
from timedinput import timedinput

from grpc import RpcError
from grpc import StatusCode

from neuro_san.client.agent_session_factory import AgentSessionFactory
from neuro_san.client.concierge_session_factory import ConciergeSessionFactory
from neuro_san.client.streaming_input_processor import StreamingInputProcessor
from neuro_san.interfaces.agent_session import AgentSession
from neuro_san.interfaces.concierge_session import ConciergeSession
from neuro_san.internals.utils.file_of_class import FileOfClass


class AgentCli:
    """
    Command line tool for communicating with a Agent service
    running in a container.
    """

    DEFAULT_INPUT: str = "DEFAULT"
    DEFAULT_PROMPT: str = "Please enter your response ('quit' to terminate):\n"

    def __init__(self):
        """
        Constructor
        """
        self.poll_timeout_seconds: float = 5.0
        self.input_timeout_seconds: float = 5000.0
        self.args = None
        self.arg_groups: Dict[str, Any] = {}

        self.session: AgentSession = None
        self.thinking_dir: str = None

    def main(self):
        """
        Main entry point for command line user interaction
        """
        self.parse_args()

        # See if we are doing a list operation
        if self.args.list or self.args.tags or self.args.tag:
            self.list()
            return

        self.open_session()
        if self.args.connectivity:
            self.connectivity()
        else:
            self.chat()

    def connectivity(self):
        """
        Perform connectivity function
        """
        empty: Dict[str, Any] = {}
        response: Dict[str, Any] = self.session.connectivity(empty)

        empty_list: List[Dict[str, Any]] = []
        for connectivity_info in response.get("connectivity_info", empty_list):
            print(f"{json.dumps(connectivity_info, indent=4, sort_keys=True)}")

    def chat(self):
        """
        Perform chat function
        """

        # Get initial user input
        user_input: str = None
        if self.args.first_prompt_file is not None:
            # Incorrectly flagged as destination of Path Traversal 4
            #   Reason: first_prompt_file was previously checked with FileOfClass.check_file()
            #           which actually does the path traversal check. CheckMarx does not
            #           recognize pathlib as a valid library with which to resolve these kinds
            #           of issues.  Furthermore, this is a client command line tool that is never
            #           used inside servers which just happens to be part of a library offering.
            prompt: Path = Path(self.args.first_prompt_file)
            with prompt.open('r', encoding="utf-8") as prompt_file:
                user_input = prompt_file.read()

        sly_data: Dict[str, Any] = None
        if self.args.sly_data is not None:
            sly_data = json.loads(self.args.sly_data)
            print(f"sly_data is {sly_data}")

        # Note: If nothing is specified the server assumes the chat_filter_type
        #       should be "MINIMAL", however for this client which is aimed at
        #       developers, we specifically want a default MAXIMAL client to
        #       show all the bells and whistles of the output that a typical
        #       end user will not care about and not appreciate the extra
        #       data charges on their cell phone.
        chat_filter: Dict[str, Any] = {
            "chat_filter_type": "MAXIMAL"
        }
        if self.args.chat_filter is not None and \
                not bool(self.args.chat_filter):
            chat_filter["chat_filter_type"] = "MINIMAL"

        message = f"""
The agent "{self.args.agent}" is not implemented on the server.

Some suggestions:
1. Did you misspell the agent name on the command line?
2. Is there a key for the agent name in the server manifest.hocon file?
3. Is the value for the agent name key in the server manifest.hocon file set to true?
4. Servers will skip manifest entries that have errors. They will also print out which
   agents they are actually serving.  Check your server output for each of these.
5. Is the server itself actually running?
"""

        empty: Dict[str, Any] = {}
        try:
            response: Dict[str, Any] = self.session.function(empty)
            if response is None:
                raise ValueError(message)
        except RpcError as exception:
            # pylint: disable=no-member
            if exception.code() is StatusCode.UNIMPLEMENTED:
                raise ValueError(message) from exception

            # If not an RpcException, then I dunno what it is.
            raise

        function: Dict[str, Any] = response.get("function", empty)
        initial_prompt: str = function.get("description")
        print(f"\n{initial_prompt}\n")

        print("To see the thinking involved with the agent:\n")
        if not self.args.thinking_dir:
            print(f"    tail -f {self.args.thinking_file}\n")
        else:
            print(f"    See any one of the files in {self.thinking_dir} for agent network chat details.\n")

        self.loop_until_done(user_input, sly_data, chat_filter)

    def loop_until_done(self, user_input: str, sly_data: Dict[str, Any],
                        chat_filter: Dict[str, Any]):
        """
        Loop trading off between user input and agent response until done.
        :param user_input: The initial user input (if any)
        :param sly_data: The initial sly data dictionary (if any)
        :param chat_filter: The chat filter dictionary to use
        """

        state: Dict[str, Any] = {
            "last_chat_response": None,
            "prompt": self.DEFAULT_PROMPT,
            "timeout": self.input_timeout_seconds,
            "num_input": 0,
            "user_input": user_input,
            "sly_data": sly_data,
            "chat_filter": chat_filter,
        }

        input_processor = StreamingInputProcessor(self.DEFAULT_INPUT,
                                                  self.args.thinking_file,
                                                  self.session,
                                                  self.thinking_dir)

        while not self.is_done(state):

            prompt = state.get("prompt")
            timeout = state.get("timeout")
            user_input = state.get("user_input")
            if user_input is None:
                if prompt is not None and len(prompt) > 0:
                    user_input = timedinput(prompt, timeout=timeout,
                                            default=self.DEFAULT_INPUT)
                else:
                    user_input = None

            if user_input == "quit":
                break

            print(f"Sending user_input {user_input}")
            state["user_input"] = user_input
            state = input_processor.process_once(state)

            print(f"\nResponse from {state.get('origin_str')}:")
            print(f"{state.get('last_chat_response')}")
            if state.get("sly_data") is not None:
                pretty_sly: str = json.dumps(state.get('sly_data'), indent=4, sort_keys=True)
                print(f"Returned sly_data is: {pretty_sly}")

            if self.args.tokens:
                print("Token Accounting:")
                print(f"{json.dumps(state.get('token_accounting'), indent=4, sort_keys=True)}")

            if self.args.response_output_file is not None:
                output_path: Path = Path(self.args.response_output_file)
                with output_path.open('w', encoding="utf-8") as output_file:
                    output_file.write(state["last_chat_response"])
                    output_file.write("\n")

    def parse_args(self):
        """
        Parse command line arguments into member variables
        """

        arg_parser = argparse.ArgumentParser()

        self.add_args(arg_parser)

        # Incorrectly flagged as source of Path Traversal 1, 2, 4, 5, 6
        # See destination in file_of_class.py for exception explanation.
        # Incorrectly flagged as source of Trust Boundary Violation 1, 2
        # See destination in agent_session_factory.py for exception explanation.
        self.args = arg_parser.parse_args()

        # Check some arguments to prevent PathTraversal scans lighting up.
        # Since this is a command-line tool not intended to be used inside a
        # Dockerfile service, we don't really care where these files come from.
        # Check anyway to give warm fuzzies to scans.
        self.args.thinking_file = FileOfClass.check_file(self.args.thinking_file, "/")
        self.args.first_prompt_file = FileOfClass.check_file(self.args.first_prompt_file, "/")

    def add_args(self, arg_parser: argparse.ArgumentParser):
        """
        Adds arguments.  Allows subclasses a chance to add their own.
        :param arg_parser: The argparse.ArgumentParser to add.
        """
        # What agent are we talking to?
        arg_parser.add_argument("--agent", type=str, default="esp_decision_assistant",
                                help="Name of the agent to talk to")

        # What agents can we connect to?
        group = arg_parser.add_argument_group(title="Agent Listings",
                                              description="What agents can we connect to?")
        group.add_argument("--list", default=False, dest="list", action="store_true",
                           help="List all available agents")
        group.add_argument("--tag", type=str,
                           help="List all agents marked with the given tag.")
        group.add_argument("--tags", default=False, dest="tags", action="store_true",
                           help="List all tags associated with agents")

        # How will we connect to neuro-san?
        group = arg_parser.add_argument_group(title="Session Type",
                                              description="How will we connect to neuro-san?")
        group.add_argument("--connection", default="direct", type=str,
                           choices=["grpc", "direct", "http", "https"],
                           help="""
The type of connection to initiate. Choices are to connect to:
    "grpc"      - an agent service via gRPC. Needs host and port.
    "http"      - an agent service via HTTP. Needs host and port.
    "https"     - an agent service via secure HTTP. Needs host and port.
    "direct"    - a session via library. (The default).
All choices require an agent name.
""")
        group.add_argument("--grpc", dest="connection", action="store_const", const="grpc",
                           help="Use a gRPC service connection")
        group.add_argument("--service", dest="connection", action="store_const", const="grpc",
                           help="Use a gRPC service connection")
        group.add_argument("--direct", dest="connection", action="store_const", const="direct",
                           help="Use a direct/library call for the chat")
        group.add_argument("--http", dest="connection", action="store_const", const="http",
                           help="Use a HTTP service connection")
        group.add_argument("--https", dest="connection", action="store_const", const="https",
                           help="Use a secure HTTP service connection. "
                                "Requires your agent server to be set up with certificates that are well known. "
                                "This is not something that our basic server setup supports out-of-the-box.")
        group.add_argument("--timeout", dest="timeout", type=float,
                           help="Timeout in seconds before giving up on connecting to a server. "
                                "By default this is None, implying we will try forever")
        self.arg_groups[group.title] = group

        # How will we connect to a server?
        group = arg_parser.add_argument_group(title="Service Connection",
                                              description="How will we connect to a server?")
        group.add_argument("--local", default=True, action="store_true",
                           help="If True (the default), assume we are running against locally running service")
        group.add_argument("--host", type=str, default=None,
                           help="hostname setting if not running locally")
        group.add_argument("--port", type=int, default=AgentSession.DEFAULT_PORT,
                           help="TCP/IP port to run the Agent gRPC service on")
        group.add_argument("--user_id", default=os.environ.get("USER"), type=str,
                           help="'user_id' metadata to send to a server for logging. Defaults to ${USER}.")
        self.arg_groups[group.title] = group

        # How can we get input to the chat client without typing it in?
        group = arg_parser.add_argument_group(title="Input Control",
                                              description="How do we get input without typing it it?")
        group.add_argument("--sly_data", type=str,
                           help="JSON string containing data that is out-of-band to the chat stream, "
                                "but is still essential to agent function")
        group.add_argument("--first_prompt_file", type=str,
                           help="File that captures the first response to the input prompt")
        group.add_argument("--max_input", type=int, default=1000000,
                           help="Maximum rounds of input to go before exiting")
        group.add_argument("--one_shot", dest="max_input", action="store_const", const=1,
                           help="Send one round of input, then exit")
        self.arg_groups[group.title] = group

        # How do we handle calls to external agents?
        group = arg_parser.add_argument_group(title="Local External Agents",
                                              description="How do handle calls to local /external agents?")
        group.add_argument("--local_externals_direct", default=False, action="store_true",
                           help="""
Have external tools that can be found in the local agent manifest use a
direct connection instead of requiring a service to be stood up.
                           """)
        group.add_argument("--local_externals_service", dest="local_externals_direct", action="store_false",
                           help="""
Have external tools that can be found in the local agent manifest use a service connection. (The default)
                           """)
        self.arg_groups[group.title] = group

        # How do we receive messages?
        group = arg_parser.add_argument_group(title="Message Filtering",
                                              description="What kind of messages will we receive?")
        group.add_argument("--maximal", default=True, dest="chat_filter", action="store_true",
                           help="Allow all messages to come from the server")
        group.add_argument("--minimal", dest="chat_filter", action="store_false",
                           help="Allow only the bare minimum of messages to come from the server")
        self.arg_groups[group.title] = group

        # How are we capturing output?
        group = arg_parser.add_argument_group(title="Output Capture",
                                              description="How will we capture output?")
        group.add_argument("--thinking_file", type=str, default="/tmp/agent_thinking.txt",
                           help="File that captures agent thinking. "
                                "This is a separate text stream from the user/assistant chat")
        group.add_argument("--thinking_dir", default=True, action="store_true",
                           help="Use the basis of the thinking_file as a directory to capture "
                                "internal agent chatter in separate files. "
                                "This is a separate text stream from the user/assistant chat. "
                                "Only available when streaming (which is the default).")
        group.add_argument("--response_output_file", type=str,
                           help="File that captures the response to the user input")
        self.arg_groups[group.title] = group

        # How are we capturing output?
        group = arg_parser.add_argument_group(title="Other Modes of Operation")
        group.add_argument("--connectivity", default=False, dest="connectivity", action="store_true",
                           help="List the connectivity of agent network nodes")
        group.add_argument("--tokens", default=False, dest="tokens", action="store_true",
                           help="Print token accounting info with every response")
        self.arg_groups[group.title] = group

    def open_session(self):
        """
        Opens a session based on the parsed command line arguments
        """
        hostname = "localhost"
        if self.args.host is not None or not self.args.local:
            hostname = self.args.host

        # Open a session with the factory
        factory: AgentSessionFactory = self.get_agent_session_factory()
        metadata: Dict[str, str] = {
            "user_id": self.args.user_id
        }
        self.session = factory.create_session(self.args.connection, self.args.agent,
                                              hostname, self.args.port, self.args.local_externals_direct,
                                              metadata, self.args.timeout)

        # Clear out the previous thinking file/dir contents
        #
        # Incorrectly flagged as destination of Path Traversal 5
        #   Reason: thinking_file was previously checked with FileOfClass.check_file()
        #           which actually does the path traversal check. CheckMarx does not
        #           recognize pathlib as a valid library with which to resolve these kinds
        #           of issues.  Furthermore, this is a client command line tool that is never
        #           used inside servers which just happens to be part of a library offering.
        if not self.args.thinking_dir:
            with open(self.args.thinking_file, "w", encoding="utf-8") as thinking:
                thinking.write("\n")
        else:
            # Use the stem of the thinking file (i.e. no ".txt" extension) as the
            # basis for the thinking directory
            self.thinking_dir, extension = os.path.splitext(self.args.thinking_file)
            _ = extension

            # Remove any contents that might be there already.
            # Writing over existing dir will just confuse output.
            if os.path.exists(self.thinking_dir):
                shutil.rmtree(self.thinking_dir)
            # Create the directory anew
            os.makedirs(self.thinking_dir)

    def get_agent_session_factory(self) -> AgentSessionFactory:
        """
        This allows subclasses to add different kinds of connections.

        :return: An AgentSessionFactory instance that will allow creation of the
                 session with the agent network.
        """
        return AgentSessionFactory()

    def is_done(self, state: Dict[str, Any]) -> bool:
        """
        :param state: The state dictionary
        :return: True if the values in the state are considered to be sufficient
                for terminating further conversation. False otherwise.
        """

        if state.get("user_input") == "quit":
            return True

        if state.get("num_input") >= self.args.max_input:
            return True

        return False

    def list(self):
        """
        List available agents via a concierge session
        """
        hostname = "localhost"
        if self.args.host is not None or not self.args.local:
            hostname = self.args.host

        metadata: Dict[str, str] = {
            "user_id": self.args.user_id
        }

        concierge_session: ConciergeSession = ConciergeSessionFactory().create_session(
            self.args.connection,
            hostname=hostname,
            port=self.args.port,
            metadata=metadata,
            connect_timeout_in_seconds=self.args.timeout)

        request_dict: Dict[str, Any] = {}
        response_dict: Dict[str, Any] = concierge_session.list(request_dict)

        empty_list: List[Dict[str, Any]] = []
        if self.args.tags:
            tags = set()
            for agent_info in response_dict.get("agents", empty_list):
                agent_tags: List[str] = agent_info.get("tags", empty_list)
                tags.update(agent_tags)
            print(f"Available tags:\n{json.dumps(list(tags), indent=4, sort_keys=True)}")

        elif self.args.tag:
            print(f"Available agents for tag {self.args.tag}:\n")
            for agent_info in response_dict.get("agents", empty_list):
                agent_tags: List[str] = agent_info.get("tags", empty_list)
                if self.args.tag in agent_tags:
                    print(json.dumps(agent_info, indent=4, sort_keys=True))

        else:
            print(f"Available agents:\n{json.dumps(response_dict, indent=4, sort_keys=True)}")


if __name__ == '__main__':
    AgentCli().main()
