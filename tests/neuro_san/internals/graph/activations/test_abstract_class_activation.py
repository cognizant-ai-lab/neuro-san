
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

from functools import partial
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Tuple
from typing import Type
from typing import Union

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from langchain_core.messages.ai import AIMessage
from typing_extensions import override

from neuro_san.interfaces.coded_tool import CodedTool
from neuro_san.interfaces.reservationist import Reservationist
from neuro_san.internals.graph.activations.branch_activation import BranchActivation
from neuro_san.internals.journals.progress_journal import ProgressJournal

from tests.neuro_san.internals.graph.activations.concrete_class_activation import ConcreteClassActivation
from tests.neuro_san.internals.graph.activations.concrete_class_activation import CREATE_RUN_CONTEXT_PATH
from tests.neuro_san.internals.graph.activations.concrete_class_activation import GET_FULL_NAME_FROM_ORIGIN_PATH
from tests.neuro_san.internals.graph.activations.failing_tool import FailingTool
from tests.neuro_san.internals.graph.activations.mock_branch_activation_tool import MockBranchActivationTool
from tests.neuro_san.internals.graph.activations.mock_coded_tool import MockCodedTool
from tests.neuro_san.internals.graph.activations.mock_coded_tool_with_constructor import MockCodedToolWithConstructor
from tests.neuro_san.internals.graph.activations.not_a_coded_tool import NotACodedTool
from tests.neuro_san.internals.graph.activations.sync_only_tool import SyncOnlyTool


class TestAbstractClassActivation(IsolatedAsyncioTestCase):
    """
    Test suite for AbstractClassActivation.
    """

    RESOLVER_PATH: str = "neuro_san.internals.graph.activations.abstract_class_activation.Resolver"

    @override
    def setUp(self) -> None:
        """
        Gives each test fresh mocks and a fresh ConcreteClassActivation.
        """
        self.mock_factory: MagicMock = TestAbstractClassActivation._create_mock_factory()
        self.basic_agent_tool_spec: Dict[str, Any] = {
            "name": "test_tool",
            "description": "Test tool"
        }
        self.mock_run_context: MagicMock = TestAbstractClassActivation._create_mock_run_context()
        with patch(CREATE_RUN_CONTEXT_PATH, return_value=self.mock_run_context):
            with patch(GET_FULL_NAME_FROM_ORIGIN_PATH, return_value="test_full_name"):
                self.activation_instance: ConcreteClassActivation = ConcreteClassActivation(
                    parent_run_context=self.mock_run_context,
                    factory=self.mock_factory,
                    args={"test_arg": "test_value"},
                    agent_tool_spec=self.basic_agent_tool_spec,
                    sly_data={"test_sly": "test_data"},
                    class_ref="test_module.TestClass"
                )

    def test_initialization(self) -> None:
        """
        Test that the activation initializes correctly.
        """
        activation_arguments: Dict[str, Any] = self.activation_instance.arguments
        test_arg: str = activation_arguments.get("test_arg")
        origin: List[Dict[str, Any]] = activation_arguments.get("origin")
        origin_str: str = activation_arguments.get("origin_str")
        progress_reporter: ProgressJournal = activation_arguments.get("progress_reporter")
        self.assertEqual(test_arg, "test_value")
        self.assertIsNotNone(origin)
        self.assertEqual(origin_str, "test_full_name")
        self.assertIsNotNone(progress_reporter)

    def test_get_full_class_ref(self) -> None:
        """
        Test that get_full_class_ref returns the correct class reference.
        """
        full_class_ref: str = self.activation_instance.get_full_class_ref()
        self.assertEqual(full_class_ref, "test_module.TestClass")

    async def test_build_success(self) -> None:
        """
        Test successful build with a valid CodedTool.
        """
        mock_tool: MockCodedTool = MockCodedTool()

        with patch.object(self.activation_instance, "resolve_class", return_value=MockCodedTool):
            with patch.object(self.activation_instance, "instantiate_coded_tool", return_value=mock_tool):
                with patch.object(self.activation_instance, "attempt_invoke", new_callable=AsyncMock,
                                  return_value="test_result"):
                    result: AIMessage = await self.activation_instance.build()

                    self.assertIsInstance(result, AIMessage)
                    self.assertEqual(result.content, "test_result")

    async def test_build_with_non_coded_tool(self) -> None:
        """
        Test build when instantiated object is not a CodedTool.
        """
        not_a_coded_tool: NotACodedTool = NotACodedTool()

        with patch.object(self.activation_instance, "resolve_class", return_value=NotACodedTool):
            with patch.object(self.activation_instance, "instantiate_coded_tool", return_value=not_a_coded_tool):
                result: AIMessage = await self.activation_instance.build()

                self.assertIsInstance(result, AIMessage)
                self.assertIn("Error:", result.content)
                self.assertIn("is not a CodedTool", result.content)

    def test_resolve_class_first_level_success(self) -> None:
        """
        Test resolving class at the most specific level.
        """
        mock_resolver: MagicMock = MagicMock()
        mock_resolver.resolve_class_in_module.return_value = MockCodedTool

        with patch(TestAbstractClassActivation.RESOLVER_PATH, return_value=mock_resolver):
            result: Type[CodedTool] = self.activation_instance.resolve_class("TestClass", "test_module")

            self.assertEqual(result, MockCodedTool)
            # Should succeed on first attempt
            self.assertEqual(mock_resolver.resolve_class_in_module.call_count, 1)

    def test_resolve_class_second_level_success(self) -> None:
        """
        Test resolving class after failing at first level.
        """
        mock_resolver_fail: MagicMock = MagicMock()
        mock_resolver_fail.resolve_class_in_module.side_effect = ValueError("Not found")

        mock_resolver_success: MagicMock = MagicMock()
        mock_resolver_success.resolve_class_in_module.return_value = MockCodedTool

        with patch(TestAbstractClassActivation.RESOLVER_PATH, side_effect=[mock_resolver_fail, mock_resolver_success]):
            result: Type[CodedTool] = self.activation_instance.resolve_class("TestClass", "test_module")

            self.assertEqual(result, MockCodedTool)
            # Should try twice (first level fails, second succeeds)
            self.assertEqual(mock_resolver_fail.resolve_class_in_module.call_count, 1)
            self.assertEqual(mock_resolver_success.resolve_class_in_module.call_count, 1)

    def test_resolve_class_all_levels_fail(self) -> None:
        """
        Test that ValueError is raised when all resolution levels fail.
        """
        mock_resolver: MagicMock = MagicMock()
        mock_resolver.resolve_class_in_module.side_effect = ValueError("Not found")

        with patch(TestAbstractClassActivation.RESOLVER_PATH, return_value=mock_resolver):
            with self.assertRaises(ValueError) as raised:
                self.activation_instance.resolve_class("TestClass", "test_module")

            error_message: str = str(raised.exception)
            self.assertIn("Could not find class", error_message)
            self.assertIn("TestClass", error_message)
            self.assertIn("test_module", error_message)

    def test_resolve_class_progressive_path_resolution(self) -> None:
        """
        Test that class resolution tries progressively higher paths.
        """
        paths_tried: List[str] = []
        resolver_factory: partial = partial(TestAbstractClassActivation._create_progressive_resolver, paths_tried)

        with patch(TestAbstractClassActivation.RESOLVER_PATH, side_effect=resolver_factory):
            result: Type[CodedTool] = self.activation_instance.resolve_class("TestClass", "test_module")

            self.assertEqual(result, MockCodedTool)
            paths_tried_count: int = len(paths_tried)
            self.assertEqual(paths_tried_count, 3)
            # Should try from most specific to most general
            self.assertEqual(paths_tried[0], "test_tools.network.subnetwork")
            self.assertEqual(paths_tried[1], "test_tools.network")
            self.assertEqual(paths_tried[2], "test_tools")

    def test_instantiate_coded_tool_standard(self) -> None:
        """
        Test instantiating a standard CodedTool with no-args constructor.
        """
        result: CodedTool = self.activation_instance.instantiate_coded_tool(MockCodedTool)

        self.assertIsInstance(result, MockCodedTool)

    def test_instantiate_coded_tool_branch_activation(self) -> None:
        """
        Test instantiating a BranchActivation + CodedTool combination.
        """
        # Patch issubclass to recognize our mock as a BranchActivation
        original_issubclass: Callable[[type, Union[type, Tuple[type, ...]]], bool] = issubclass
        issubclass_stand_in: partial = partial(TestAbstractClassActivation._patched_issubclass, original_issubclass)

        with patch("builtins.issubclass", side_effect=issubclass_stand_in):
            result: CodedTool = self.activation_instance.instantiate_coded_tool(MockBranchActivationTool)

            self.assertIsInstance(result, MockBranchActivationTool)
            # Verify it was initialized with correct parameters
            branch_tool: MockBranchActivationTool = result
            init_params: Dict[str, Any] = branch_tool.get_init_params()
            init_factory: MagicMock = init_params.get("factory")
            init_args: Dict[str, Any] = init_params.get("args")
            self.assertEqual(init_factory, self.mock_factory)
            self.assertEqual(init_args, self.activation_instance.arguments)

    def test_instantiate_coded_tool_with_constructor_fails(self) -> None:
        """
        Test that instantiating a CodedTool with required constructor args raises TypeError.
        """
        with self.assertRaises(TypeError) as raised:
            self.activation_instance.instantiate_coded_tool(MockCodedToolWithConstructor)

        error_message: str = str(raised.exception)
        self.assertIn("must take no arguments to its constructor", error_message)

    async def test_attempt_invoke_async_success(self) -> None:
        """
        Test successful async invocation of a CodedTool.
        """
        mock_tool: MockCodedTool = MockCodedTool()

        result: Any = await self.activation_instance.attempt_invoke(mock_tool, {"arg": "value"}, {"sly": "data"})

        self.assertEqual(result, "mock_result")

    async def test_attempt_invoke_sync_fallback(self) -> None:
        """
        Test fallback to synchronous invoke when async_invoke not implemented.
        """
        mock_tool: SyncOnlyTool = SyncOnlyTool()
        mock_executor: MagicMock = MagicMock()
        mock_loop: MagicMock = MagicMock()
        mock_loop.run_in_executor = AsyncMock(return_value="sync_result")
        mock_executor.get_event_loop.return_value = mock_loop

        invocation_context: MagicMock = self.activation_instance.run_context.get_invocation_context()
        invocation_context.get_asyncio_executor.return_value = mock_executor

        result: Any = await self.activation_instance.attempt_invoke(mock_tool, {"arg": "value"}, {"sly": "data"})

        self.assertEqual(result, "sync_result")
        mock_loop.run_in_executor.assert_called_once()

    async def test_attempt_invoke_with_exception(self) -> None:
        """
        Test that exceptions during invocation are caught and returned as error strings.
        """
        mock_tool: FailingTool = FailingTool()

        result: Any = await self.activation_instance.attempt_invoke(mock_tool, {"arg": "value"}, {"sly": "data"})

        self.assertIn("Error:", result)
        self.assertIn("Tool failed", result)

    def test_arguments_initialization_with_origin(self) -> None:
        """
        Test that origin arguments are set correctly during initialization.
        """
        with patch(CREATE_RUN_CONTEXT_PATH, return_value=self.mock_run_context):
            with patch(GET_FULL_NAME_FROM_ORIGIN_PATH, return_value="full_name"):
                activation: ConcreteClassActivation = ConcreteClassActivation(
                    parent_run_context=self.mock_run_context,
                    factory=self.mock_factory,
                    args=None,
                    agent_tool_spec=self.basic_agent_tool_spec,
                    sly_data={},
                    class_ref="test.Class"
                )

        origin: List[Dict[str, Any]] = activation.arguments.get("origin")
        origin_str: str = activation.arguments.get("origin_str")
        self.assertIsNotNone(origin)
        self.assertEqual(origin_str, "full_name")

    def test_arguments_do_not_override_existing_origin(self) -> None:
        """
        Test that existing origin arguments are not overridden.
        """
        existing_origin: List[Dict[str, Any]] = [{"custom": "origin"}]

        with patch(CREATE_RUN_CONTEXT_PATH, return_value=self.mock_run_context):
            with patch(GET_FULL_NAME_FROM_ORIGIN_PATH, return_value="full_name"):
                activation: ConcreteClassActivation = ConcreteClassActivation(
                    parent_run_context=self.mock_run_context,
                    factory=self.mock_factory,
                    args={
                        "origin": existing_origin,
                        "origin_str": "custom_str"
                    },
                    agent_tool_spec=self.basic_agent_tool_spec,
                    sly_data={},
                    class_ref="test.Class"
                )

        origin: List[Dict[str, Any]] = activation.arguments.get("origin")
        origin_str: str = activation.arguments.get("origin_str")
        self.assertEqual(origin, existing_origin)
        self.assertEqual(origin_str, "custom_str")

    def test_reservationist_initialization_when_allowed(self) -> None:
        """
        Test that reservationist is initialized when allowed in spec.
        """
        mock_reservationist: MagicMock = MagicMock()
        invocation_context: MagicMock = self.mock_run_context.get_invocation_context()
        invocation_context.get_reservationist.return_value = mock_reservationist

        agent_tool_spec: Dict[str, Any] = {
            "name": "test_tool",
            "allow": {
                "reservations": True
            }
        }

        with patch(CREATE_RUN_CONTEXT_PATH, return_value=self.mock_run_context):
            with patch(GET_FULL_NAME_FROM_ORIGIN_PATH, return_value="full_name"):
                activation: ConcreteClassActivation = ConcreteClassActivation(
                    parent_run_context=self.mock_run_context,
                    factory=self.mock_factory,
                    args={},
                    agent_tool_spec=agent_tool_spec,
                    sly_data={},
                    class_ref="test.Class"
                )

        self.assertIsNotNone(activation.reservationist)
        reservationist: Reservationist = activation.arguments.get("reservationist")
        self.assertIsNotNone(reservationist)

    # The static methods below are this class's own helpers, not overrides.

    @staticmethod
    def _create_mock_factory() -> MagicMock:
        """
        Creates a mock AgentToolFactory.

        :return: A MagicMock that stands in for an AgentToolFactory
        """
        inspector: MagicMock = MagicMock()
        inspector.get_network_name.return_value = "network/subnetwork"

        factory: MagicMock = MagicMock()
        factory.get_agent_tool_paths.return_value = ["test_tools.network.subnetwork"]
        factory.get_name_from_spec.return_value = "test_agent"
        factory.get_agent_network.return_value = inspector
        return factory

    @staticmethod
    def _create_mock_run_context() -> MagicMock:
        """
        Creates a mock RunContext.

        :return: A MagicMock that stands in for a RunContext
        """
        context: MagicMock = MagicMock()

        # Create a mock journal with async write_message
        mock_journal: MagicMock = MagicMock()
        mock_journal.write_message = AsyncMock()
        context.get_journal.return_value = mock_journal

        context.get_origin.return_value = [{"agent": "test_agent"}]

        invocation_context: MagicMock = MagicMock()
        invocation_context.get_reservationist.return_value = None
        invocation_context.get_asyncio_executor.return_value = MagicMock()
        context.get_invocation_context.return_value = invocation_context
        return context

    @staticmethod
    def _create_progressive_resolver(paths_tried: List[str], packages: List[str]) -> MagicMock:
        """
        Creates a mock Resolver that fails for the first two packages and succeeds after.

        :param paths_tried: The list that collects the first package of each call
        :param packages: The list of packages the Resolver is created with
        :return: A MagicMock that stands in for a Resolver
        """
        paths_tried.append(packages[0])
        resolver: MagicMock = MagicMock()

        paths_tried_count: int = len(paths_tried)
        if paths_tried_count <= 2:  # Fail first two attempts
            resolver.resolve_class_in_module.side_effect = ValueError("Not found")
        else:  # Succeed on third attempt
            resolver.resolve_class_in_module.return_value = MockCodedTool

        return resolver

    @staticmethod
    def _patched_issubclass(original_issubclass: Callable[[type, Union[type, Tuple[type, ...]]], bool],
                            checked_class: type, classinfo: Union[type, Tuple[type, ...]]) -> bool:
        """
        Stands in for issubclass() so that MockBranchActivationTool counts as a BranchActivation.

        :param original_issubclass: The real issubclass() to call for every other check
        :param checked_class: The class to check
        :param classinfo: The class or tuple of classes to check against
        :return: True if checked_class counts as a subclass of classinfo
        """
        if checked_class == MockBranchActivationTool and classinfo == BranchActivation:
            return True
        return original_issubclass(checked_class, classinfo)
