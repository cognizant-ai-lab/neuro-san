
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


class AsyncHopper:
    """
    An interface whose clients store things for later use.
    """

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
        raise NotImplementedError
