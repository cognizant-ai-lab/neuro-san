
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
from typing import List

from neuro_san.internals.graph.activations.calling_activation import CallingActivation
from neuro_san.internals.interfaces.front_man import FrontMan
from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.run_context.interfaces.run import Run


class FrontManActivation(CallingActivation, FrontMan):
    """
    A CallingActivation implementation which is the root of the call graph.
    """

    async def create_any_resources(self):
        """
        Creates resources that will be used throughout the lifetime of the component.
        """
        await self.create_resources()

    async def submit_message(self, user_input: str) -> List[Any]:
        """
        Entry-point method for callers of the root of the Activation tree.

        :param user_input: An input string from the user.
        :return: A list of response messages for the run
        """
        # Initialize our return value
        messages: List[Any] = []

        current_run: Run = await self.run_context.submit_message(user_input)

        terminate = False
        while not terminate:
            if self.run_context is None:
                # Breaking from inside a container during cleanup can yield a None
                # run_context
                break

            current_run = await self.run_context.wait_on_run(current_run, self.journal)

            if current_run.requires_action():
                current_run = await self.make_tool_function_calls(current_run)
            else:
                # Needs to get more information from the user on the basic task
                # of collecting information from the user about the current run.
                if self.run_context is None:
                    # Breaking from inside a container during cleanup can yield a None
                    # run_context
                    break
                messages = await self.run_context.get_response()
                terminate = True

        return messages

    def update_invocation_context(self, invocation_context: InvocationContext):
        """
        Update internal state based on the InvocationContext instance passed in.
        :param invocation_context: The context policy container that pertains to the invocation
        """
        self.journal = invocation_context.get_journal()
        if self.run_context is not None:
            self.run_context.update_invocation_context(invocation_context)

    async def build(self) -> str:
        """
        Main entry point to the class.

        :return: A string representing a List of messages produced during this process.
        """
        # This is never called for a FrontMan, but is needed to satisfy the
        # class heirarchy stemming from CallableActivation.
        # A FrontMan is not Callable.
        raise NotImplementedError

    async def delete_any_resources(self):
        """
        Cleans up after any allocated resources
        """
        await self.delete_resources(None)
