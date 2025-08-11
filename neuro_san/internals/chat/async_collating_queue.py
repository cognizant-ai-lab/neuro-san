
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
from typing import AsyncIterator
from typing import Dict

from janus import Queue

from neuro_san.internals.interfaces.async_hopper import AsyncHopper


class AsyncCollatingQueue(AsyncIterator, AsyncHopper):
    """
    AsyncIterator instance to asynchronously iterate over/consume the contents of
    a Queue as they come in.
    """
    # Constant for the end key
    END_KEY: str = "end"

    # Constant for the end message to be put in a Queue when all the messages are done
    END_MESSAGE: Dict[str, Any] = {END_KEY: True}

    def __init__(self, queue: Queue = None):
        """
        Constructor

        :param queue: The queue we will be iterating over.
                      Default value is None, indicating a standard Queue will be used.
        """
        self.queue: Queue = queue
        if self.queue is None:
            self.queue = Queue()

    def get_queue(self) -> Queue:
        """
        :return: The Queue associated with this instance
        """
        return self.queue

    def __aiter__(self) -> AsyncIterator[Dict[str, Any]]:
        """
        Self-identify as an AsyncIterator when called upon by
        the Python async framework.
        """
        return self

    async def __anext__(self) -> Dict[str, Any]:
        """
        :return: Blocks waiting to return the next item on the queue.
                Will throw StopAsyncIteration when the final item is detected
                via the is_final_item() method..
        """
        message = await self.queue.async_q.get()
        if self.is_final_item(message):
            raise StopAsyncIteration

        return message

    async def put(self, item: Any, synchronous: bool = False):
        """
        Fulfills AsyncHopper interface

        :param item: The item to put on the queue.
        :param synchronous: When False (the default), we use the asynchronous-side
                of the queue for our put() operation.  This is generally what
                would be expected inside an async call, which is why it is the default.
                When True, we use the synchronous side of the queue for put().
                This ends up being necessary when each end of the queue is serviced
                in a different asyncio event loop.
        """
        if synchronous:
            self.queue.sync_q.put(item)
        else:
            await self.queue.async_q.put(item)

    async def put_final_item(self, synchronous: bool = False):
        """
        Puts the final item on the queue indicating that no more data will
        be on the queue and the consumer's iteration can cease when it sees
        this item.
        :param synchronous: When False (the default), we use the asynchronous-side
                of the queue for our put() operation.  This is generally what
                would be expected inside an async call, which is why it is the default.
                When True, we use the synchronous side of the queue for put().
                This ends up being necessary when each end of the queue is serviced
                in a different asyncio event loop.
        """
        await self.put(self.END_MESSAGE, synchronous)

    def is_final_item(self, item: Any) -> bool:
        """
        :param item: An item that has just been pulled off the queue
        :return: True if this item is considered the marker for the
                 end of data. False otherwise.
        """
        return isinstance(item, Dict) and item.get(self.END_KEY) is not None

    def close(self):
        """
        Close this queue
        """
        self.queue.close()
