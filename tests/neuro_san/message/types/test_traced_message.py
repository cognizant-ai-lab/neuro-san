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
from typing import List

from unittest import TestCase

from langchain_core.load import dumpd

from neuro_san.message.types.agent_framework_message import AgentFrameworkMessage
from neuro_san.message.types.agent_message import AgentMessage
from neuro_san.message.types.agent_progress_message import AgentProgressMessage
from neuro_san.message.types.agent_tool_result_message import AgentToolResultMessage
from neuro_san.message.types.traced_message import TracedMessage
from neuro_san.message.utils.sly_data_redactor import SlyDataRedactor


class TestTracedMessage(TestCase):
    """
    Tests that TracedMessage subclasses serialize through LangChain's dumpd(),
    which tracers such as LangChainTracer call on chat model input messages.
    """

    def test_dumpd_all_subclasses(self) -> None:
        """
        Tests that dumpd() serializes every TracedMessage subclass as a LangChain constructor.
        """
        messages: List[TracedMessage] = [
            AgentFrameworkMessage(content="framework"),
            AgentMessage(content="agent"),
            AgentProgressMessage(content="progress"),
            AgentToolResultMessage(content="tool result"),
        ]

        # Each subclass must serialize without the deprecated-attribute ValueError.
        message: TracedMessage = None
        for message in messages:
            serialized: Dict[str, Any] = dumpd(message)
            self.assertEqual(serialized.get("type"), "constructor")
            self.assertEqual(serialized.get("kwargs").get("content"), message.content)

    def test_dumpd_trace_source_copy(self) -> None:
        """
        Tests that dumpd() serializes a trace_source copy with its fields moved into additional_kwargs.
        """
        source: AgentMessage = AgentMessage(content="hello", structure={"key": "value"})
        traced: AgentMessage = AgentMessage(trace_source=source)

        serialized: Dict[str, Any] = dumpd(traced)
        additional_kwargs: Dict[str, Any] = serialized.get("kwargs").get("additional_kwargs")
        self.assertEqual(additional_kwargs, {"content": "hello", "structure": {"key": "value"}})

    def test_dumpd_trace_source_redacts_sly_data(self) -> None:
        """
        Tests that dumpd() of an AgentFrameworkMessage trace_source copy redacts sly_data values
        except those the redactor allows, while keeping all sly_data keys.
        """
        spec: Dict[str, Any] = {
            "allow": {
                "to_tracing": {
                    "sly_data": ["visible"]
                }
            }
        }
        redactor: SlyDataRedactor = SlyDataRedactor(spec, config_keys=["allow.to_tracing.sly_data"])
        sly_data: Dict[str, Any] = {"visible": "shown", "secret": "api-key-value"}
        source: AgentFrameworkMessage = AgentFrameworkMessage(content="done", sly_data=sly_data,
                                                              redactor=redactor)
        traced: AgentFrameworkMessage = AgentFrameworkMessage(trace_source=source)

        serialized: Dict[str, Any] = dumpd(traced)
        additional_kwargs: Dict[str, Any] = serialized.get("kwargs").get("additional_kwargs")
        self.assertEqual(additional_kwargs.get("sly_data"), {"visible": "shown", "secret": "<redacted>"})
        self.assertNotIn("api-key-value", str(serialized))

        # The original sly_data must not be mutated by redaction.
        self.assertEqual(sly_data, {"visible": "shown", "secret": "api-key-value"})

    def test_dumpd_trace_source_redacts_sly_data_without_redactor(self) -> None:
        """
        Tests that dumpd() of an AgentFrameworkMessage trace_source copy redacts every
        sly_data value when no redactor is given.
        """
        source: AgentFrameworkMessage = AgentFrameworkMessage(content="done", sly_data={"secret": "api-key-value"})
        traced: AgentFrameworkMessage = AgentFrameworkMessage(trace_source=source)

        serialized: Dict[str, Any] = dumpd(traced)
        additional_kwargs: Dict[str, Any] = serialized.get("kwargs").get("additional_kwargs")
        self.assertEqual(additional_kwargs.get("sly_data"), {"secret": "<redacted>"})
        self.assertNotIn("api-key-value", str(serialized))
