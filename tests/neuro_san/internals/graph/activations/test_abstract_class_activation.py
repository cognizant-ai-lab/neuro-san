
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

import logging
import os
import sys

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from langchain_core.messages.ai import AIMessage
import pytest

from neuro_san.interfaces.coded_tool import CodedTool
from neuro_san.internals.graph.activations.abstract_class_activation import AbstractClassActivation
from neuro_san.internals.graph.activations.branch_activation import BranchActivation

CREATE_RUN_CONTEXT_PATH = (
    "neuro_san.internals.graph.activations.abstract_class_activation."
    "RunContextFactory.create_run_context"
)
GET_FULL_NAME_FROM_ORIGIN_PATH = (
    "neuro_san.internals.graph.activations.abstract_class_activation."
    "Origination.get_full_name_from_origin"
)
RESOLVER_PATH = "neuro_san.internals.graph.activations.abstract_class_activation.Resolver"
# pylint: disable=redefined-outer-name


class ConcreteClassActivation(AbstractClassActivation):
    """Concrete implementation for testing purposes."""
    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def __init__(self, parent_run_context, factory, arguments, agent_tool_spec, sly_data, class_ref: str):
        super().__init__(parent_run_context, factory, arguments, agent_tool_spec, sly_data)
        self._class_ref = class_ref

    def get_full_class_ref(self) -> str:
        return self._class_ref


class MockCodedTool(CodedTool):
    """Mock CodedTool for testing."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        return "mock_result"


class MockBranchActivationTool(CodedTool):
    """Mock tool that inherits from BranchActivation pattern.

    This simulates a CodedTool that also acts as a BranchActivation,
    requiring the full constructor signature.
    """
    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def __init__(self, run_context, factory, arguments, agent_tool_spec, sly_data):
        # Store the initialization parameters for verification
        self.init_params = {
            'run_context': run_context,
            'factory': factory,
            'arguments': arguments,
            'agent_tool_spec': agent_tool_spec,
            'sly_data': sly_data
        }
        # Mark this as a BranchActivation-like class
        self._is_branch_activation = True

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        return "branch_activation_result"


# Helper function to make MockBranchActivationTool appear as a BranchActivation subclass
def is_branch_activation_subclass(cls):
    """Check if class should be treated as BranchActivation."""
    return hasattr(cls, '_is_branch_activation') or issubclass(cls, BranchActivation)


class MockCodedToolWithConstructor(CodedTool):
    """Mock CodedTool with constructor arguments (invalid pattern)."""

    def __init__(self, required_arg):
        self.required_arg = required_arg

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        return "should_not_reach"


@pytest.fixture
def mock_run_context():
    """Create a mock RunContext."""
    context = MagicMock()

    # Create a mock journal with async write_message
    mock_journal = MagicMock()
    mock_journal.write_message = AsyncMock()
    context.get_journal.return_value = mock_journal

    context.get_origin.return_value = {"agent": "test_agent"}
    context.get_invocation_context.return_value = MagicMock()
    context.get_invocation_context().get_reservationist.return_value = None
    context.get_invocation_context().get_asyncio_executor.return_value = MagicMock()
    return context


@pytest.fixture
def mock_factory():
    """Create a mock AgentToolFactory."""
    factory = MagicMock()
    factory.get_agent_tool_path.return_value = "test_tools.network.subnetwork"
    factory.agent_network.get_network_name.return_value = "network/subnetwork"
    factory.get_name_from_spec.return_value = "test_agent"
    return factory


@pytest.fixture
def basic_agent_tool_spec():
    """Create a basic agent tool spec."""
    return {
        "name": "test_tool",
        "description": "Test tool"
    }


@pytest.fixture
def activation_instance(mock_run_context, mock_factory, basic_agent_tool_spec):
    """Create a ConcreteClassActivation instance for testing."""
    with patch(CREATE_RUN_CONTEXT_PATH, return_value=mock_run_context):
        with patch(GET_FULL_NAME_FROM_ORIGIN_PATH, return_value="test_full_name"):
            activation = ConcreteClassActivation(
                parent_run_context=mock_run_context,
                factory=mock_factory,
                arguments={"test_arg": "test_value"},
                agent_tool_spec=basic_agent_tool_spec,
                sly_data={"test_sly": "test_data"},
                class_ref="test_module.TestClass"
            )
            return activation


class TestAbstractClassActivation:
    """Test suite for AbstractClassActivation."""

    def test_initialization(self, activation_instance):
        """Test that the activation initializes correctly."""
        assert activation_instance.arguments["test_arg"] == "test_value"
        assert activation_instance.arguments.get("origin") is not None
        assert activation_instance.arguments.get("origin_str") == "test_full_name"
        assert activation_instance.arguments.get("progress_reporter") is not None

    def test_get_full_class_ref(self, activation_instance):
        """Test that get_full_class_ref returns the correct class reference."""
        assert activation_instance.get_full_class_ref() == "test_module.TestClass"

    @pytest.mark.asyncio
    async def test_build_success(self, activation_instance):
        """Test successful build with a valid CodedTool."""
        mock_tool = MockCodedTool()

        with patch.object(activation_instance, 'resolve_class', return_value=MockCodedTool):
            with patch.object(activation_instance, 'instantiate_coded_tool', return_value=mock_tool):
                with patch.object(activation_instance, 'attempt_invoke', new_callable=AsyncMock,
                                  return_value="test_result"):
                    result = await activation_instance.build()

                    assert isinstance(result, AIMessage)
                    assert result.content == "test_result"

    @pytest.mark.asyncio
    async def test_build_with_non_coded_tool(self, activation_instance):
        """Test build when instantiated object is not a CodedTool."""
        class NotACodedTool:
            """A class that does not inherit from CodedTool."""

        with patch.object(activation_instance, 'resolve_class', return_value=NotACodedTool):
            with patch.object(activation_instance, 'instantiate_coded_tool', return_value=NotACodedTool()):
                result = await activation_instance.build()

                assert isinstance(result, AIMessage)
                assert "Error:" in result.content
                assert "is not a CodedTool" in result.content

    def test_resolve_class_first_level_success(self, activation_instance):
        """Test resolving class at the most specific level."""
        mock_resolver = MagicMock()
        mock_resolver.resolve_class_in_module.return_value = MockCodedTool

        with patch(RESOLVER_PATH, return_value=mock_resolver):
            result = activation_instance.resolve_class("TestClass", "test_module")

            assert result == MockCodedTool
            # Should succeed on first attempt
            assert mock_resolver.resolve_class_in_module.call_count == 1

    def test_resolve_class_second_level_success(self, activation_instance):
        """Test resolving class after failing at first level."""
        mock_resolver_fail = MagicMock()
        mock_resolver_fail.resolve_class_in_module.side_effect = ValueError("Not found")

        mock_resolver_success = MagicMock()
        mock_resolver_success.resolve_class_in_module.return_value = MockCodedTool

        with patch(RESOLVER_PATH, side_effect=[mock_resolver_fail, mock_resolver_success]):
            result = activation_instance.resolve_class("TestClass", "test_module")

            assert result == MockCodedTool
            # Should try twice (first level fails, second succeeds)
            assert mock_resolver_fail.resolve_class_in_module.call_count == 1
            assert mock_resolver_success.resolve_class_in_module.call_count == 1

    def test_resolve_class_all_levels_fail(self, activation_instance):
        """Test that ValueError is raised when all resolution levels fail."""
        mock_resolver = MagicMock()
        mock_resolver.resolve_class_in_module.side_effect = ValueError("Not found")

        with patch(RESOLVER_PATH, return_value=mock_resolver):
            with pytest.raises(ValueError) as exc_info:
                activation_instance.resolve_class("TestClass", "test_module")

            error_message = str(exc_info.value)
            assert "Could not find class" in error_message
            assert "TestClass" in error_message
            assert "test_module" in error_message

    def test_resolve_class_progressive_path_resolution(self, activation_instance):
        """Test that class resolution tries progressively higher paths."""
        call_count = 0
        paths_tried = []

        def mock_resolver_factory(packages):
            nonlocal call_count
            paths_tried.append(packages[0])
            resolver = MagicMock()

            if call_count < 2:  # Fail first two attempts
                resolver.resolve_class_in_module.side_effect = ValueError("Not found")
                call_count += 1
            else:  # Succeed on third attempt
                resolver.resolve_class_in_module.return_value = MockCodedTool

            return resolver

        with patch(RESOLVER_PATH, side_effect=mock_resolver_factory):
            result = activation_instance.resolve_class("TestClass", "test_module")

            assert result == MockCodedTool
            assert len(paths_tried) == 3
            # Should try from most specific to most general
            assert paths_tried[0] == "test_tools.network.subnetwork"
            assert paths_tried[1] == "test_tools.network"
            assert paths_tried[2] == "test_tools"

    def test_instantiate_coded_tool_standard(self, activation_instance):
        """Test instantiating a standard CodedTool with no-args constructor."""
        result = activation_instance.instantiate_coded_tool(MockCodedTool)

        assert isinstance(result, MockCodedTool)

    def test_instantiate_coded_tool_branch_activation(self, activation_instance, mock_factory):
        """Test instantiating a BranchActivation + CodedTool combination."""
        # Patch issubclass to recognize our mock as a BranchActivation
        original_issubclass = __builtins__['issubclass']

        def patched_issubclass(cls, classinfo):
            if cls == MockBranchActivationTool and classinfo == BranchActivation:
                return True
            return original_issubclass(cls, classinfo)

        with patch('builtins.issubclass', side_effect=patched_issubclass):
            result = activation_instance.instantiate_coded_tool(MockBranchActivationTool)

            assert isinstance(result, MockBranchActivationTool)
            # Verify it was initialized with correct parameters
            assert result.init_params['factory'] == mock_factory
            assert result.init_params['arguments'] == activation_instance.arguments

    def test_instantiate_coded_tool_with_constructor_fails(self, activation_instance):
        """Test that instantiating a CodedTool with required constructor args raises TypeError."""
        with pytest.raises(TypeError) as exc_info:
            activation_instance.instantiate_coded_tool(MockCodedToolWithConstructor)

        error_message = str(exc_info.value)
        assert "must take no arguments to its constructor" in error_message

    @pytest.mark.asyncio
    async def test_attempt_invoke_async_success(self, activation_instance):
        """Test successful async invocation of a CodedTool."""
        mock_tool = MockCodedTool()

        result = await activation_instance.attempt_invoke(mock_tool, {"arg": "value"}, {"sly": "data"})

        assert result == "mock_result"

    @pytest.mark.asyncio
    async def test_attempt_invoke_sync_fallback(self, activation_instance):
        """Test fallback to synchronous invoke when async_invoke not implemented."""
        class SyncOnlyTool(CodedTool):
            """Mock CodedTool with only sync invoke."""
            def invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
                return "sync_result"

            async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
                raise NotImplementedError()

        mock_tool = SyncOnlyTool()
        mock_executor = MagicMock()
        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(return_value="sync_result")
        mock_executor.get_event_loop.return_value = mock_loop

        invocation_context = activation_instance.run_context.get_invocation_context()
        invocation_context.get_asyncio_executor.return_value = mock_executor

        result = await activation_instance.attempt_invoke(mock_tool, {"arg": "value"}, {"sly": "data"})

        assert result == "sync_result"
        mock_loop.run_in_executor.assert_called_once()

    @pytest.mark.asyncio
    async def test_attempt_invoke_with_exception(self, activation_instance):
        """Test that exceptions during invocation are caught and returned as error strings."""
        class FailingTool(CodedTool):
            """Mock CodedTool that raises an exception."""
            async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
                raise RuntimeError("Tool failed")

        mock_tool = FailingTool()

        result = await activation_instance.attempt_invoke(mock_tool, {"arg": "value"}, {"sly": "data"})

        assert "Error:" in result
        assert "Tool failed" in result

    def test_arguments_initialization_with_origin(self, mock_run_context, mock_factory, basic_agent_tool_spec):
        """Test that origin arguments are set correctly during initialization."""
        with patch(CREATE_RUN_CONTEXT_PATH, return_value=mock_run_context):
            with patch(GET_FULL_NAME_FROM_ORIGIN_PATH, return_value="full_name"):
                activation = ConcreteClassActivation(
                    parent_run_context=mock_run_context,
                    factory=mock_factory,
                    arguments=None,
                    agent_tool_spec=basic_agent_tool_spec,
                    sly_data={},
                    class_ref="test.Class"
                )

                assert activation.arguments.get("origin") is not None
                assert activation.arguments["origin_str"] == "full_name"

    def test_arguments_do_not_override_existing_origin(self, mock_run_context, mock_factory, basic_agent_tool_spec):
        """Test that existing origin arguments are not overridden."""
        existing_origin = {"custom": "origin"}

        with patch(CREATE_RUN_CONTEXT_PATH, return_value=mock_run_context):
            with patch(GET_FULL_NAME_FROM_ORIGIN_PATH, return_value="full_name"):
                activation = ConcreteClassActivation(
                    parent_run_context=mock_run_context,
                    factory=mock_factory,
                    arguments={"origin": existing_origin, "origin_str": "custom_str"},
                    agent_tool_spec=basic_agent_tool_spec,
                    sly_data={},
                    class_ref="test.Class"
                )

                assert activation.arguments["origin"] == existing_origin
                assert activation.arguments["origin_str"] == "custom_str"

    def test_reservationist_initialization_when_allowed(self, mock_run_context, mock_factory):
        """Test that reservationist is initialized when allowed in spec."""
        mock_reservationist = MagicMock()
        invocation_context = mock_run_context.get_invocation_context()
        invocation_context.get_reservationist.return_value = mock_reservationist

        agent_tool_spec = {
            "name": "test_tool",
            "allow": {
                "reservations": True
            }
        }

        with patch(CREATE_RUN_CONTEXT_PATH, return_value=mock_run_context):
            with patch(GET_FULL_NAME_FROM_ORIGIN_PATH, return_value="full_name"):
                activation = ConcreteClassActivation(
                    parent_run_context=mock_run_context,
                    factory=mock_factory,
                    arguments={},
                    agent_tool_spec=agent_tool_spec,
                    sly_data={},
                    class_ref="test.Class"
                )

                assert activation.reservationist is not None
                assert activation.arguments.get("reservationist") is not None


FIXTURE_TOOL_PATH_PACKAGE = "tests.neuro_san.internals.graph.activations.tool_path_fixture"
CANARY_PACKAGE = "tests.neuro_san.internals.graph.activations"


@pytest.fixture
def fixture_factory():
    """Create a mock AgentToolFactory whose tool path points at real fixture modules."""
    factory = MagicMock()
    factory.get_agent_tool_path.return_value = f"{FIXTURE_TOOL_PATH_PACKAGE}.my_network"
    factory.agent_network.get_network_name.return_value = "my_network"
    factory.get_name_from_spec.return_value = "test_agent"
    return factory


@pytest.fixture
def fixture_activation(mock_run_context, fixture_factory, basic_agent_tool_spec):
    """Create an activation whose class resolution runs unmocked against fixture modules."""
    with patch(CREATE_RUN_CONTEXT_PATH, return_value=mock_run_context):
        with patch(GET_FULL_NAME_FROM_ORIGIN_PATH, return_value="test_full_name"):
            return ConcreteClassActivation(
                parent_run_context=mock_run_context,
                factory=fixture_factory,
                arguments={},
                agent_tool_spec=basic_agent_tool_spec,
                sly_data={},
                class_ref="unused.Unused"
            )


class TestToolPathOnlyResolution:
    """
    Tests for the AGENT_TOOL_PATH_ONLY environment variable, run against real
    fixture modules with no Resolver mocks so that actual import behavior is
    what is asserted.
    """

    def test_default_mode_resolves_fully_qualified_ref(self, fixture_activation):
        """Test that with the flag off, a fully-qualified ref to a module outside
        AGENT_TOOL_PATH resolves by direct import (backwards-compatible behavior)."""
        with patch.dict(os.environ):
            os.environ.pop("AGENT_TOOL_PATH_ONLY", None)
            cls = fixture_activation.resolve_class(
                "CanaryTool", f"{CANARY_PACKAGE}.resolution_canary_default")
        assert cls.__name__ == "CanaryTool"

    def test_tool_path_only_blocks_fully_qualified_ref_without_importing(self, fixture_activation):
        """Test that strict mode rejects a fully-qualified ref outside AGENT_TOOL_PATH
        and, critically, never imports the referenced module — importing executes
        module-level code, which is the vulnerability the flag closes."""
        module_path = f"{CANARY_PACKAGE}.resolution_canary_strict"
        sys.modules.pop(module_path, None)

        with patch.dict(os.environ, {"AGENT_TOOL_PATH_ONLY": "true"}):
            with pytest.raises(ValueError) as exc_info:
                fixture_activation.resolve_class("CanaryTool", module_path)

        assert module_path not in sys.modules
        assert "AGENT_TOOL_PATH_ONLY" in str(exc_info.value)

    def test_tool_path_only_resolves_network_specific_tool(self, fixture_activation):
        """Test that strict mode still resolves a tool at the network-specific level."""
        with patch.dict(os.environ, {"AGENT_TOOL_PATH_ONLY": "true"}):
            cls = fixture_activation.resolve_class("NetworkTool", "network_tool")
        assert cls.__name__ == "NetworkTool"

    def test_tool_path_only_resolves_shared_tool(self, fixture_activation):
        """Test that strict mode still resolves a shared tool one level up the hierarchy."""
        with patch.dict(os.environ, {"AGENT_TOOL_PATH_ONLY": "true"}):
            cls = fixture_activation.resolve_class("SharedTool", "shared_tool")
        assert cls.__name__ == "SharedTool"

    def test_tool_path_only_resolves_shipped_toolbox_coded_tool(
            self, mock_run_context, basic_agent_tool_spec):
        """Test that strict mode still resolves the coded tools shipped in
        neuro_san/coded_tools, as referenced by the default toolbox info file."""
        factory = MagicMock()
        factory.get_agent_tool_path.return_value = "neuro_san.coded_tools.date_time_timezone"
        factory.agent_network.get_network_name.return_value = "date_time_timezone"
        factory.get_name_from_spec.return_value = "current_date_time"

        with patch(CREATE_RUN_CONTEXT_PATH, return_value=mock_run_context):
            with patch(GET_FULL_NAME_FROM_ORIGIN_PATH, return_value="test_full_name"):
                activation = ConcreteClassActivation(
                    parent_run_context=mock_run_context,
                    factory=factory,
                    arguments={},
                    agent_tool_spec=basic_agent_tool_spec,
                    sly_data={},
                    class_ref="unused.Unused"
                )

        with patch.dict(os.environ, {"AGENT_TOOL_PATH_ONLY": "true"}):
            cls = activation.resolve_class("GetCurrentDateTime", "get_current_date_time")
        assert cls.__name__ == "GetCurrentDateTime"

    def test_default_mode_still_resolves_tool_path_refs(self, fixture_activation):
        """Test that with the flag off, tool-path-relative refs resolve as before."""
        with patch.dict(os.environ):
            os.environ.pop("AGENT_TOOL_PATH_ONLY", None)
            cls = fixture_activation.resolve_class("NetworkTool", "network_tool")
        assert cls.__name__ == "NetworkTool"

    def test_unrestricted_resolution_notice_logged_once(self, fixture_activation, caplog):
        """Test that the flag-off notice is logged exactly once per process."""
        # pylint: disable=protected-access
        AbstractClassActivation._unrestricted_notice_logged = False
        with patch.dict(os.environ):
            os.environ.pop("AGENT_TOOL_PATH_ONLY", None)
            with caplog.at_level(logging.INFO):
                fixture_activation.resolve_class("NetworkTool", "network_tool")
                fixture_activation.resolve_class("SharedTool", "shared_tool")

        assert caplog.text.count("AGENT_TOOL_PATH_ONLY is not enabled") == 1
