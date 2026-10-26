
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

from neuro_san.message.processors.basic_message_processor import BasicMessageProcessor

from tests.load_tests.unit.fake_session import FakeSession


class FakeProcessor:
    """
    Stand-in for StreamingInputProcessor that drains the stream.
    """

    def __init__(self, session: FakeSession, **_kwargs: Any) -> None:
        """
        Constructor.

        :param session: The session whose streaming_chat is consumed
        :param _kwargs: The real processor's constructor arguments, ignored
        """
        self._session: FakeSession = session

    def get_message_processor(self) -> BasicMessageProcessor:
        """
        :return: A real message processor that has seen the stream's sly_data
        """
        processor: BasicMessageProcessor = BasicMessageProcessor()
        processor.process_message({
            "type": "AGENT_FRAMEWORK", "chat_context": {},
            "sly_data": {"reservation_id": "abc-1"},
        })
        return processor

    def process_once(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Consume every streamed message, as the real processor does.

        :param state: The request state
        :return: A copy of the state with the answer filled in
        """
        _: Dict[str, Any]
        # Read the whole stream.
        for _ in self._session.streaming_chat({}):
            pass
        updated: Dict[str, Any] = dict(state)
        updated["last_chat_response"] = "answer"
        return updated
