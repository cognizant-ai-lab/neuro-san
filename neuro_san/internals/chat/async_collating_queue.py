
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
from typing import AsyncIterator
from typing import Dict

from janus import Queue

from neuro_san.internals.interfaces.async_hopper import AsyncHopper


class AsyncCollatingQueue(AsyncIterator, AsyncHopper):
    """
    AsyncIterator instance to asynchronously iterate over/consume the contents of
    a Queue as they come in.

    Note that this is not considered a LingeringResource, as different instances
    of this class are used in different situations where close_of_request() and
    close_of_work() inconsistent in these different use cases.
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
        self.last_item_sent: bool = False

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

    async def put(self, item: Any, synchronous: bool = False, check_last_item_sent: bool = True):
        """
        Fulfills AsyncHopper interface

        :param item: The item to put on the queue.
        :param synchronous: When False (the default), we use the asynchronous-side
                of the queue for our put() operation.  This is generally what
                would be expected inside an async call, which is why it is the default.
                When True, we use the synchronous side of the queue for put().
                This ends up being necessary when each end of the queue is serviced
                in a different asyncio event loop.
        :param check_last_item_sent: When True (the default), this method will
                not put anything if the last item was already sent.
        """
        if check_last_item_sent and self.last_item_sent:
            # If the last message was sent, don't put anything else
            # This controls unbounded queue growth when there is no longer a consumer.
            return

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
        if self.last_item_sent:
            return
        self.last_item_sent = True
        await self.put(self.END_MESSAGE, synchronous, check_last_item_sent=False)

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

    def reset(self):
        """
        Allows more messages to be sent on this queue
        """
        self.last_item_sent = False
