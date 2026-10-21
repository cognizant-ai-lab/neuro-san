
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

from typing import Any
from typing import Dict
from typing import List

from unittest import TestCase
from unittest.mock import MagicMock
from unittest.mock import patch

from typing_extensions import override

from langchain_core.tools.base import BaseTool
from langchain_core.tools.base import BaseToolkit

from neuro_san.internals.run_context.langchain.toolbox.toolbox_factory import ToolboxFactory

FIXTURE_MODULE: str = "tests.neuro_san.internals.run_context.langchain.toolbox.real_tool_fixture"

RESOLVER_PATH: str = "leaf_common.resolution.resolver.Resolver.resolve_class_in_module"
VALIDATOR_PATH: str = (
    "neuro_san.internals.run_context.langchain.util.argument_validator.ArgumentValidator.check_invalid_args"
)


class TestToolboxFactory(TestCase):
    """
    Simplified test suite for ToolboxFactory.
    """

    @override
    def setUp(self) -> None:
        """
        Gives each test a fresh instance of ToolboxFactory.
        """
        self.factory: ToolboxFactory = ToolboxFactory()

    def test_load_only_loads_once(self) -> None:
        """
        Test that load() reads hocon files on the first call only.
        """
        # Keep the test hermetic: no user toolbox info file from the environment.
        self.factory.toolbox_info_file = None
        restorer_path: str = "neuro_san.internals.run_context.langchain.toolbox.toolbox_factory.ToolboxInfoRestorer"
        infos: Dict[str, Any] = {"some_tool": {"class": "mock_package.mock_module.SomeTool"}}
        with patch(restorer_path) as mock_restorer:
            mock_restorer.return_value.restore.return_value = infos

            self.assertFalse(self.factory.loaded)
            self.factory.load()
            self.assertTrue(self.factory.loaded)
            self.assertEqual(self.factory.toolbox_infos, infos)

            # A second load() must be a no-op: no further file reads,
            # and the previously loaded infos are kept.
            self.factory.load()
            mock_restorer.return_value.restore.assert_called_once()
            self.assertEqual(self.factory.toolbox_infos, infos)

    def test_create_toolbox_returns_single_base_tool(self) -> None:
        """
        Test that the tool is resolved with correct arguments.
        """

        self.factory.toolbox_infos = {
            "test_tool": {
                "class": "mock_package.mock_module.TestTool",
                "args": {
                    "param1": "value1",
                    "param2": "value2"
                }
            }
        }

        # Mock user-provided arguments
        user_args: Dict[str, Any] = {"param2": "user_value", "param3": "extra_value"}

        with patch(RESOLVER_PATH) as mock_resolver, patch(VALIDATOR_PATH) as mock_check_invalid:
            mock_tool_class = MagicMock(spec=BaseTool)
            mock_resolver.return_value = mock_tool_class

            mock_instance = MagicMock(spec=BaseTool)
            mock_instance.name = MagicMock(spec=str)
            mock_instance.tags = MagicMock(spec=list)
            mock_tool_class.return_value = mock_instance

            tool: BaseTool = self.factory.create_tool_from_toolbox("test_tool", user_args)

            # Ensure the correct class was resolved
            mock_resolver.assert_called_once_with("TestTool", module_name="mock_module")

            # Ensure ArgumentValidator.check_invalid_args was called
            mock_check_invalid.assert_called_once()

            # Ensure the tool was initialized with the correct merged args
            mock_tool_class.assert_called_once_with(param1="value1", param2="user_value", param3="extra_value")

            # Ensure the returned tool is an instance of the mocked class
            self.assertIs(tool, mock_instance)

    def test_create_toolbox_with_removed_tool_gives_migration_error(self) -> None:
        """
        Test that a reference to a removed requests_* tool explains the removal
        and how to migrate, rather than raising a generic 'not defined' error.
        """
        self.factory.toolbox_infos = {}

        with self.assertRaisesRegex(ValueError, "deprecated langchain-community") as context:
            self.factory.create_tool_from_toolbox("requests_get", {})
        error_text: str = str(context.exception)
        self.assertIn("AGENT_TOOLBOX_INFO_FILE", error_text)

    def test_create_toolbox_with_partial_override_of_removed_tool(self) -> None:
        """
        Test that a class-less entry for a removed tool also gets the migration
        error. A user toolbox file that overrides only the args of a removed
        entry has no 'class', because the bundled default does not define
        removed tools. It should not die on a generic missing-'class' message.
        """
        self.factory.toolbox_infos = {
            "requests_get": {"args": {"headers": {"Authorization": "Bearer token"}}},
        }

        with self.assertRaisesRegex(ValueError, "deprecated langchain-community"):
            self.factory.create_tool_from_toolbox("requests_get", {})

    def test_create_toolbox_missing_class_names_the_tool(self) -> None:
        """
        Test that the missing-'class' error names the offending tool.
        """
        self.factory.toolbox_infos = {
            "my_tool": {"args": {"param": "value"}},
        }

        with self.assertRaisesRegex(ValueError, "Tool 'my_tool' is missing required key: 'class'"):
            self.factory.create_tool_from_toolbox("my_tool", {})

    def test_empty_tool_entry_reports_missing_class(self) -> None:
        """
        Test that an empty (but present) tool entry is reported as missing
        'class' rather than as not defined, from both toolbox entry points.
        """
        self.factory.toolbox_infos = {
            "empty_tool": {},
        }

        with self.assertRaisesRegex(ValueError, "Tool 'empty_tool' is missing required key: 'class'"):
            self.factory.create_tool_from_toolbox("empty_tool", {})

        with self.assertRaisesRegex(ValueError, "Tool 'empty_tool' is missing required key: 'class'"):
            self.factory.get_shared_coded_tool_class("empty_tool")

    def test_create_toolbox_with_unknown_tool_names_sources(self) -> None:
        """
        Test that an unknown tool name reports the searched sources by name,
        both with and without a user toolbox info file.
        """
        self.factory.toolbox_infos = {}

        self.factory.toolbox_info_file = None
        with self.assertRaisesRegex(ValueError, "not defined in the default toolbox info file."):
            self.factory.create_tool_from_toolbox("no_such_tool", {})

        self.factory.toolbox_info_file = "/path/to/user_toolbox.hocon"
        with self.assertRaisesRegex(ValueError, "or in /path/to/user_toolbox.hocon"):
            self.factory.create_tool_from_toolbox("no_such_tool", {})

    def test_create_toolbox_real_tool_unmocked(self) -> None:
        """
        Test tool creation with no mocks: a real BaseTool subclass and a real
        nested wrapper class are resolved from their class paths, validated,
        instantiated, and tagged — the same path an operator's toolbox info
        file entry takes.
        """
        self.factory.toolbox_infos = {
            "real_tool": {
                "class": f"{FIXTURE_MODULE}.RealTool",
                "args": {
                    "max_results": 3,
                    "api_wrapper": {
                        "class": f"{FIXTURE_MODULE}.RealApiWrapper",
                        "args": {"timeout": 30},
                    },
                },
            }
        }

        user_args: Dict[str, Any] = {"max_results": 7}
        tool: BaseTool = self.factory.create_tool_from_toolbox("real_tool", user_args=user_args, agent_name="my_agent")

        self.assertIsInstance(tool, BaseTool)
        self.assertEqual(tool.name, "my_agent")
        self.assertEqual(tool.tags, ["langchain_tool"])
        # user_args override the toolbox-file args; nested wrapper args survive
        self.assertEqual(tool.max_results, 7)
        self.assertEqual(tool.api_wrapper.timeout, 30)

    def test_langchain_community_class_logs_sunset_warning(self) -> None:
        """
        Test that a tool whose class comes from langchain-community logs the
        sunset warning on creation.
        """
        self.factory.toolbox_infos = {
            "community_tool": {"class": "langchain_community.some_module.SomeTool"},
        }

        with patch(RESOLVER_PATH) as mock_resolver, patch(VALIDATOR_PATH):
            mock_tool_class = MagicMock(spec=BaseTool)
            mock_resolver.return_value = mock_tool_class

            mock_instance = MagicMock(spec=BaseTool)
            mock_instance.name = MagicMock(spec=str)
            mock_instance.tags = MagicMock(spec=list)
            mock_tool_class.return_value = mock_instance

            # ToolboxFactory logs through logging.warning(), so the record goes to the root logger.
            with self.assertLogs(level=logging.WARNING) as captured_logs:
                self.factory.create_tool_from_toolbox("community_tool", {})

        log_text: str = "\n".join(captured_logs.output)
        self.assertIn("langchain-community", log_text)
        self.assertIn("sunset", log_text)

    def test_get_shared_coded_tool_class_unknown_tool_raises(self) -> None:
        """
        Test that unknown and removed tool names raise the same clear
        ValueErrors as create_tool_from_toolbox(), instead of crashing with
        AttributeError on the missing toolbox entry.
        """
        self.factory.toolbox_infos = {
            "known_tool": {"class": "some_module.SomeCodedTool"},
        }
        self.factory.toolbox_info_file = None

        known_tool_class: str = self.factory.get_shared_coded_tool_class("known_tool")
        self.assertEqual(known_tool_class, "some_module.SomeCodedTool")

        with self.assertRaisesRegex(ValueError, "not defined in the default toolbox info file."):
            self.factory.get_shared_coded_tool_class("no_such_tool")

        with self.assertRaisesRegex(ValueError, "deprecated langchain-community"):
            self.factory.get_shared_coded_tool_class("requests_get")

    def test_create_toolbox_with_invalid_class_value(self) -> None:
        """
        Test that a non-string or empty 'class' value raises a clear ValueError
        from both toolbox entry points.
        """
        bad_classes: List[Any] = [None, 123, ""]
        for bad_class in bad_classes:
            with self.subTest(bad_class=bad_class):
                self.factory.toolbox_infos = {
                    "bad_tool": {
                        "class": bad_class
                    }
                }

                with self.assertRaisesRegex(ValueError, "must be a non-empty string"):
                    self.factory.create_tool_from_toolbox("bad_tool", {})

                with self.assertRaisesRegex(ValueError, "must be a non-empty string"):
                    self.factory.get_shared_coded_tool_class("bad_tool")

    def test_create_toolbox_with_toolkit_constructor(self) -> None:
        """
        Test the toolkit instantiates with constructor.
        """
        self.factory.toolbox_infos = {
            "test_toolkit": {
                "class": "mock_package.mock_module.TestToolkit",
                "args": {
                    "param1": "value1",
                    "param2": "value2"
                }
            }
        }

        # Mock user-provided arguments
        user_args: Dict[str, Any] = {"param2": "user_value", "param3": "extra_value"}

        with patch(RESOLVER_PATH) as mock_resolver, patch(VALIDATOR_PATH) as mock_check_invalid:
            mock_toolkit_class = MagicMock(spec=BaseToolkit)
            mock_resolver.return_value = mock_toolkit_class

            mock_instance = MagicMock()
            mock_tool_1 = MagicMock(spec=BaseTool)
            mock_tool_1.name = MagicMock(spec=str)
            mock_tool_1.tags = MagicMock(spec=list)
            mock_tool_2 = MagicMock(spec=BaseTool)
            mock_tool_2.name = MagicMock(spec=str)
            mock_tool_2.tags = MagicMock(spec=list)
            mock_tools: List[MagicMock] = [mock_tool_1, mock_tool_2]
            mock_instance.get_tools.return_value = mock_tools
            mock_toolkit_class.return_value = mock_instance

            tools: List[BaseTool] = self.factory.create_tool_from_toolbox("test_toolkit", user_args)

            # Ensure the correct class was resolved
            mock_resolver.assert_called_once_with("TestToolkit", module_name="mock_module")

            # Ensure ArgumentValidator.check_invalid_args was called
            mock_check_invalid.assert_called_once()

            # Ensure the tool was initialized with the correct merged args
            mock_toolkit_class.assert_called_once_with(param1="value1", param2="user_value", param3="extra_value")

            self.assertEqual(tools, mock_tools)
            mock_instance.get_tools.assert_called_once()

    def test_create_toolbox_with_toolkit_class_method(self) -> None:
        """
        Test the toolkit that instantiates with class method.
        """
        self.factory.toolbox_infos = {
            "method_toolkit": {
                "class": "mock_package.mock_module.TestToolkit",
                "args": {
                    "param1": "value1",
                    "param2": "value2"
                }
            }
        }

        # Mock user-provided arguments
        user_args: Dict[str, Any] = {"param2": "user_value", "param3": "extra_value"}

        with patch(RESOLVER_PATH) as mock_resolver, patch(VALIDATOR_PATH) as mock_check_invalid:
            # Mock the toolkit class
            mock_toolkit_class = MagicMock()
            mock_resolver.return_value = mock_toolkit_class

            # Mock the class method
            mock_toolkit_instance = MagicMock()
            mock_toolkit_class.from_tool_api_wrapper.return_value = mock_toolkit_instance

            # Mock get_tools() returning a list of tools
            mock_tool_1 = MagicMock(spec=BaseTool)
            mock_tool_1.name = MagicMock(spec=str)
            mock_tool_1.tags = MagicMock(spec=list)
            mock_tool_2 = MagicMock(spec=BaseTool)
            mock_tool_2.name = MagicMock(spec=str)
            mock_tool_2.tags = MagicMock(spec=list)
            mock_toolkit_instance.get_tools.return_value = [mock_tool_1, mock_tool_2]

            # Call the factory method
            tools: List[BaseTool] = self.factory.create_tool_from_toolbox("method_toolkit", user_args)

            # Ensure the correct method was called instead of the constructor
            mock_toolkit_class.from_tool_api_wrapper.assert_called_once_with(
                param1="value1", param2="user_value", param3="extra_value")

            # Ensure ArgumentValidator.check_invalid_args was called
            mock_check_invalid.assert_called_once()

            # Ensure get_tools() was called
            mock_toolkit_instance.get_tools.assert_called_once()

            # Ensure the returned tools match the mocked tools
            self.assertEqual(tools, [mock_tool_1, mock_tool_2])
