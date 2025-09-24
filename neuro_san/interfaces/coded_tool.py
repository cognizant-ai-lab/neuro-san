
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


class CodedTool:
    """
    Interface contract for a coded tool to squelch the anti-pattern of
    Static Cling.

    Upon activation by the agent hierarchy, a CodedTool will have either its
    async_invoke() (preferred) or synchronous invoke() method called by the system.

    Implementations are expected to clean up after themselves.
    """

    def invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        """
        This method is provided as a convenience for an "easy" start to using
        coded-tools.

        Know that any CodedTool is run within the confines of a Python asynchronous
        EventLoop. Any synchronous blocking that happens - like making a call to a
        web service over a socket, or something that inherently sleep()s - *will* also
        block all other agent operations.  This is not so bad in a low-traffic or
        test environment, but when scaling up, you really really want to embrace
        and override the async_invoke() method below instead of this one.

        The idea is to allow easy development of CodedTools and use of invoke() is not so bad in a
        low-traffic or test environment. However, when scaling up, you really really want to embrace
        and override the async_invoke() method below instead of this one if at all possible,
        as it is inherently more efficient.

        :param args: An argument dictionary whose keys are the parameters
                to the coded tool and whose values are the values passed for them
                by the calling agent.  This dictionary is to be treated as read-only.
        :param sly_data: A dictionary whose keys are defined by the agent hierarchy,
                but whose values are meant to be kept out of the chat stream.

                This dictionary is largely to be treated as read-only.
                It is possible to add key/value pairs to this dict that do not
                yet exist as a bulletin board, as long as the responsibility
                for which coded_tool publishes new entries is well understood
                by the agent chain implementation and the coded_tool implementation
                adding the data is not invoke()-ed more than once.
        :return: A return value that goes into the chat stream.
        """
        # Do not raise an exception here, but pass instead.
        # This allows for fully asynchronous CodedTools to not have to worry about
        # the synchronous bits.

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        """
        Called when the coded tool is invoked asynchronously by the agent hierarchy.
        Strongly consider overriding this method instead of the "easier" synchronous
        invoke() version above when the possibility of making any kind of call that could block
        (like sleep() or a socket read/write out to a web service) is within the
        scope of your CodedTool and can be done asynchronously, especially within
        the context of your CodedTool running within a server.

        If you find your CodedTools can't help but synchronously block,
        strongly consider looking into using the asyncio.to_thread() function
        to not block the EventLoop for other requests.
        See: https://docs.python.org/3/library/asyncio-task.html#asyncio.to_thread
        Example:
            async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
                return await asyncio.to_thread(self.invoke, args, sly_data)

        :param args: An argument dictionary whose keys are the parameters
                to the coded tool and whose values are the values passed for them
                by the calling agent.  This dictionary is to be treated as read-only.
        :param sly_data: A dictionary whose keys are defined by the agent hierarchy,
                but whose values are meant to be kept out of the chat stream.

                This dictionary is largely to be treated as read-only.
                It is possible to add key/value pairs to this dict that do not
                yet exist as a bulletin board, as long as the responsibility
                for which coded_tool publishes new entries is well understood
                by the agent chain implementation and the coded_tool implementation
                adding the data is not invoke()-ed more than once.
        :return: A return value that goes into the chat stream.
        """
        raise NotImplementedError
