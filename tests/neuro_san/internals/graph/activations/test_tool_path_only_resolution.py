
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

import os
import sys

from logging import INFO
from typing import Any
from typing import Dict
from typing import Optional
from typing import Type

from unittest import TestCase
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from typing_extensions import override

from neuro_san.internals.graph.activations.abstract_class_activation import AbstractClassActivation

from tests.neuro_san.internals.graph.activations.concrete_class_activation import ConcreteClassActivation
from tests.neuro_san.internals.graph.activations.concrete_class_activation import CREATE_RUN_CONTEXT_PATH
from tests.neuro_san.internals.graph.activations.concrete_class_activation import GET_FULL_NAME_FROM_ORIGIN_PATH


FIXTURE_TOOL_PATH_PACKAGE: str = "tests.neuro_san.internals.graph.activations.tool_path_fixture"
# A canary module deliberately outside any tool path; see resolution_canary.py.
CANARY_MODULE: str = "tests.neuro_san.internals.graph.activations.resolution_canary"


class TestToolPathOnlyResolution(TestCase):
    """
    Tests for the AGENT_TOOL_PATH_ONLY environment variable, run against real
    fixture modules with no Resolver mocks so that actual import behavior is
    what is asserted.
    """

    @override
    def setUp(self) -> None:
        """
        Create a mock RunContext and an activation pointed at the test tool_path_fixture hierarchy.
        """
        self.mock_run_context = MagicMock()

        # Create a mock journal with async write_message
        mock_journal = MagicMock()
        mock_journal.write_message = AsyncMock()
        self.mock_run_context.get_journal.return_value = mock_journal

        # The same mock is returned on every get_invocation_context() call
        invocation_context = MagicMock()
        invocation_context.get_reservationist.return_value = None
        invocation_context.get_asyncio_executor.return_value = MagicMock()

        self.mock_run_context.get_origin.return_value = {"agent": "test_agent"}
        self.mock_run_context.get_invocation_context.return_value = invocation_context

        fixture_tool_path: str = f"{FIXTURE_TOOL_PATH_PACKAGE}.my_network"
        self.fixture_activation: ConcreteClassActivation = self.make_activation(fixture_tool_path, "my_network")

    def test_default_mode_resolves_fully_qualified_ref(self) -> None:
        """
        Test that with the flag off, a fully-qualified ref to a module outside
        AGENT_TOOL_PATH resolves by direct import (backwards-compatible behavior).
        """
        with patch.dict(os.environ):
            os.environ.pop("AGENT_TOOL_PATH_ONLY", None)
            resolved_class: Type[Any] = self.fixture_activation.resolve_class("CanaryTool", CANARY_MODULE)
            self.assertEqual(resolved_class.__name__, "CanaryTool")

    def test_tool_path_only_blocks_fully_qualified_ref_without_importing(self) -> None:
        """
        Test that strict mode rejects a fully-qualified ref outside AGENT_TOOL_PATH
        and, critically, never imports the referenced module — importing executes
        module-level code, which is the vulnerability the flag closes.
        """
        sys.modules.pop(CANARY_MODULE, None)

        with patch.dict(os.environ, {"AGENT_TOOL_PATH_ONLY": "true"}):
            with self.assertRaises(ValueError) as raised_error:
                self.fixture_activation.resolve_class("CanaryTool", CANARY_MODULE)

            self.assertNotIn(CANARY_MODULE, sys.modules.keys())
            self.assertIn("AGENT_TOOL_PATH_ONLY", str(raised_error.exception))

    def test_tool_path_only_resolves_network_specific_tool(self) -> None:
        """
        Test that strict mode still resolves a tool at the network-specific level.
        """
        with patch.dict(os.environ, {"AGENT_TOOL_PATH_ONLY": "true"}):
            resolved_class: Type[Any] = self.fixture_activation.resolve_class("NetworkTool", "network_tool")
            self.assertEqual(resolved_class.__name__, "NetworkTool")

    def test_tool_path_only_resolves_shared_tool(self) -> None:
        """
        Test that strict mode still resolves a shared tool one level up the hierarchy.
        """
        with patch.dict(os.environ, {"AGENT_TOOL_PATH_ONLY": "true"}):
            resolved_class: Type[Any] = self.fixture_activation.resolve_class("SharedTool", "shared_tool")
            self.assertEqual(resolved_class.__name__, "SharedTool")

    def test_tool_path_only_accepts_boolean_like_values(self) -> None:
        """
        Test that common boolean-like spellings enable the flag, so an operator
        setting it like other neuro-san flags is not silently left unrestricted.
        """
        sys.modules.pop(CANARY_MODULE, None)
        for truthy_value in ("true", "True", "TRUE", "yes", " true "):
            with patch.dict(os.environ, {"AGENT_TOOL_PATH_ONLY": truthy_value}):
                with self.assertRaises(ValueError):
                    self.fixture_activation.resolve_class("CanaryTool", CANARY_MODULE)
                self.assertNotIn(CANARY_MODULE, sys.modules.keys())

    def test_tool_path_only_resolves_shipped_toolbox_coded_tool(self) -> None:
        """
        Test that strict mode still resolves the coded tools shipped in
        neuro_san/coded_tools, as referenced by the default toolbox info file.
        """
        activation: ConcreteClassActivation = self.make_activation(
            "neuro_san.coded_tools.date_time_timezone", "date_time_timezone", agent_name="current_date_time")

        with patch.dict(os.environ, {"AGENT_TOOL_PATH_ONLY": "true"}):
            resolved_class: Type[Any] = activation.resolve_class("GetCurrentDateTime", "get_current_date_time")
            self.assertEqual(resolved_class.__name__, "GetCurrentDateTime")

    def test_unrestricted_resolution_notice_logged_once(self) -> None:
        """
        Test that the flag-off notice is logged exactly once per process.
        """
        # pylint: disable=protected-access
        AbstractClassActivation._unrestricted_notice_logged = False
        with patch.dict(os.environ):
            os.environ.pop("AGENT_TOOL_PATH_ONLY", None)
            with self.assertLogs(level=INFO) as captured_logs:
                self.fixture_activation.resolve_class("NetworkTool", "network_tool")
                self.fixture_activation.resolve_class("SharedTool", "shared_tool")

            # Each output entry is one "LEVEL:logger:message" line; count the notice across all of them.
            log_text: str = "\n".join(captured_logs.output)
            notice_count: int = log_text.count("AGENT_TOOL_PATH_ONLY is not enabled")
            self.assertEqual(notice_count, 1)

    def make_activation(self, agent_tool_path: str, network_name: str,
                        agent_name: str = "test_agent") -> ConcreteClassActivation:
        """
        Build a ConcreteClassActivation whose class resolution runs unmocked against
        real fixture modules, with the factory pointed at the given tool path.

        :param agent_tool_path: The dotted package the factory reports as the tool path.
        :param network_name: The agent network name the factory reports.
        :param agent_name: The name the factory reports for the spec.
        :return: A ready-to-use ConcreteClassActivation.
        """
        inspector = MagicMock()
        inspector.get_network_name.return_value = network_name

        factory = MagicMock()
        factory.get_agent_tool_path.return_value = agent_tool_path
        factory.get_name_from_spec.return_value = agent_name
        factory.get_agent_network.return_value = inspector

        agent_tool_spec: Dict[str, Any] = {"name": agent_name, "description": "Test tool"}
        activation: Optional[ConcreteClassActivation] = None
        with patch(CREATE_RUN_CONTEXT_PATH, return_value=self.mock_run_context):
            with patch(GET_FULL_NAME_FROM_ORIGIN_PATH, return_value="test_full_name"):
                activation = ConcreteClassActivation(
                    parent_run_context=self.mock_run_context,
                    factory=factory,
                    args={},
                    agent_tool_spec=agent_tool_spec,
                    sly_data={},
                    class_ref="unused.Unused"
                )
        return activation
