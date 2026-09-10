
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

import logging
import sys

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from neuro_san.internals.graph.activations.abstract_class_activation import AbstractClassActivation

from tests.neuro_san.internals.graph.activations.concrete_class_activation import ConcreteClassActivation
from tests.neuro_san.internals.graph.activations.concrete_class_activation import CREATE_RUN_CONTEXT_PATH
from tests.neuro_san.internals.graph.activations.concrete_class_activation import GET_FULL_NAME_FROM_ORIGIN_PATH


FIXTURE_TOOL_PATH_PACKAGE = "tests.neuro_san.internals.graph.activations.tool_path_fixture"
# A canary module deliberately outside any tool path; see resolution_canary.py.
CANARY_MODULE = "tests.neuro_san.internals.graph.activations.resolution_canary"


def make_activation(mock_run_context, agent_tool_path: str, network_name: str,
                    agent_name: str = "test_agent") -> "ConcreteClassActivation":
    """
    Build a ConcreteClassActivation whose class resolution runs unmocked against
    real fixture modules, with the factory pointed at the given tool path.

    :param mock_run_context: The mock RunContext to inject.
    :param agent_tool_path: The dotted package the factory reports as the tool path.
    :param network_name: The agent network name the factory reports.
    :param agent_name: The name the factory reports for the spec.
    :return: A ready-to-use ConcreteClassActivation.
    """
    factory = MagicMock()
    factory.get_agent_tool_path.return_value = agent_tool_path
    factory.agent_network.get_network_name.return_value = network_name
    factory.get_name_from_spec.return_value = agent_name

    with patch(CREATE_RUN_CONTEXT_PATH, return_value=mock_run_context):
        with patch(GET_FULL_NAME_FROM_ORIGIN_PATH, return_value="test_full_name"):
            return ConcreteClassActivation(
                parent_run_context=mock_run_context,
                factory=factory,
                args={},
                agent_tool_spec={"name": agent_name, "description": "Test tool"},
                sly_data={},
                class_ref="unused.Unused"
            )


@pytest.fixture
def fixture_activation(mock_run_context):
    """An activation pointed at the test tool_path_fixture hierarchy."""
    return make_activation(
        mock_run_context, f"{FIXTURE_TOOL_PATH_PACKAGE}.my_network", "my_network")


# pylint: disable=redefined-outer-name
class TestToolPathOnlyResolution:
    """
    Tests for the AGENT_TOOL_PATH_ONLY environment variable, run against real
    fixture modules with no Resolver mocks so that actual import behavior is
    what is asserted.
    """

    def test_default_mode_resolves_fully_qualified_ref(self, fixture_activation, monkeypatch):
        """Test that with the flag off, a fully-qualified ref to a module outside
        AGENT_TOOL_PATH resolves by direct import (backwards-compatible behavior)."""
        monkeypatch.delenv("AGENT_TOOL_PATH_ONLY", raising=False)
        cls = fixture_activation.resolve_class("CanaryTool", CANARY_MODULE)
        assert cls.__name__ == "CanaryTool"

    def test_tool_path_only_blocks_fully_qualified_ref_without_importing(
            self, fixture_activation, monkeypatch):
        """Test that strict mode rejects a fully-qualified ref outside AGENT_TOOL_PATH
        and, critically, never imports the referenced module — importing executes
        module-level code, which is the vulnerability the flag closes."""
        sys.modules.pop(CANARY_MODULE, None)

        monkeypatch.setenv("AGENT_TOOL_PATH_ONLY", "true")
        with pytest.raises(ValueError) as exc_info:
            fixture_activation.resolve_class("CanaryTool", CANARY_MODULE)

        assert CANARY_MODULE not in sys.modules
        assert "AGENT_TOOL_PATH_ONLY" in str(exc_info.value)

    def test_tool_path_only_resolves_network_specific_tool(self, fixture_activation, monkeypatch):
        """Test that strict mode still resolves a tool at the network-specific level."""
        monkeypatch.setenv("AGENT_TOOL_PATH_ONLY", "true")
        cls = fixture_activation.resolve_class("NetworkTool", "network_tool")
        assert cls.__name__ == "NetworkTool"

    def test_tool_path_only_resolves_shared_tool(self, fixture_activation, monkeypatch):
        """Test that strict mode still resolves a shared tool one level up the hierarchy."""
        monkeypatch.setenv("AGENT_TOOL_PATH_ONLY", "true")
        cls = fixture_activation.resolve_class("SharedTool", "shared_tool")
        assert cls.__name__ == "SharedTool"

    def test_tool_path_only_accepts_boolean_like_values(self, fixture_activation, monkeypatch):
        """Test that common boolean-like spellings enable the flag, so an operator
        setting it like other neuro-san flags is not silently left unrestricted."""
        sys.modules.pop(CANARY_MODULE, None)
        for truthy in ("true", "True", "TRUE", "yes", " true "):
            monkeypatch.setenv("AGENT_TOOL_PATH_ONLY", truthy)
            with pytest.raises(ValueError):
                fixture_activation.resolve_class("CanaryTool", CANARY_MODULE)
            assert CANARY_MODULE not in sys.modules

    def test_tool_path_only_resolves_shipped_toolbox_coded_tool(self, mock_run_context, monkeypatch):
        """Test that strict mode still resolves the coded tools shipped in
        neuro_san/coded_tools, as referenced by the default toolbox info file."""
        activation = make_activation(
            mock_run_context, "neuro_san.coded_tools.date_time_timezone",
            "date_time_timezone", agent_name="current_date_time")

        monkeypatch.setenv("AGENT_TOOL_PATH_ONLY", "true")
        cls = activation.resolve_class("GetCurrentDateTime", "get_current_date_time")
        assert cls.__name__ == "GetCurrentDateTime"

    def test_unrestricted_resolution_notice_logged_once(self, fixture_activation, caplog, monkeypatch):
        """Test that the flag-off notice is logged exactly once per process."""
        # pylint: disable=protected-access
        AbstractClassActivation._unrestricted_notice_logged = False
        monkeypatch.delenv("AGENT_TOOL_PATH_ONLY", raising=False)
        with caplog.at_level(logging.INFO):
            fixture_activation.resolve_class("NetworkTool", "network_tool")
            fixture_activation.resolve_class("SharedTool", "shared_tool")

        assert caplog.text.count("AGENT_TOOL_PATH_ONLY is not enabled") == 1
