
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

from unittest.mock import patch, MagicMock

from langchain.tools import BaseTool
from langchain_community.agent_toolkits.base import BaseToolkit
import pytest

from neuro_san.internals.run_context.langchain.toolbox.toolbox_factory import ToolboxFactory

RESOLVER_PATH = "leaf_common.config.resolver.Resolver.resolve_class_in_module"
VALIDATIOR_PATH = (
    "neuro_san.internals.run_context.langchain.util.argument_validator."
    "ArgumentValidator.check_invalid_args"
)


class TestBaseToolFactory:
    """Simplified test suite for ToolboxFactory."""

    @pytest.fixture
    def factory(self):
        """Fixture to provide a fresh instance of ToolboxFactory."""
        return ToolboxFactory()

    def test_create_toolbox_returns_single_base_tool(self, factory):
        """Test that the tool is resolved with correct arguments."""

        factory.toolbox_infos = {
            "test_tool": {
                "class": "mock_package.mock_module.TestTool",
                "args": {
                    "param1": "value1",
                    "param2": "value2"
                }
            }
        }

        # Mock user-provided arguments
        user_args = {"param2": "user_value", "param3": "extra_value"}

        with patch(RESOLVER_PATH) as mock_resolver, patch(VALIDATIOR_PATH) as mock_check_invalid:
            mock_tool_class = MagicMock(spec=BaseTool)
            mock_resolver.return_value = mock_tool_class

            mock_instance = MagicMock(spec=BaseTool)
            mock_tool_class.return_value = mock_instance

            tool = factory.create_tool_from_toolbox("test_tool", user_args)

            # Ensure the correct class was resolved
            mock_resolver.assert_called_once_with("TestTool", module_name="mock_module")

            # Ensure _check_invalid_args was called
            mock_check_invalid.assert_called_once()

            # Ensure the tool was initialized with the correct merged args
            mock_tool_class.assert_called_once_with(param1="value1", param2="user_value", param3="extra_value")

            # Ensure the returned tool is an instance of the mocked class
            assert tool is mock_instance

    def test_create_toolbox_with_toolkit_constructor(self, factory):
        """Test the toolkit instantiates with constructor."""
        factory.toolbox_infos = {
            "test_toolkit": {
                "class": "mock_package.mock_module.TestToolkit",
                "args": {
                    "param1": "value1",
                    "param2": "value2"
                }
            }
        }

        # Mock user-provided arguments
        user_args = {"param2": "user_value", "param3": "extra_value"}

        with patch(RESOLVER_PATH) as mock_resolver, patch(VALIDATIOR_PATH) as mock_check_invalid:
            mock_toolkit_class = MagicMock(spec=BaseToolkit)
            mock_resolver.return_value = mock_toolkit_class

            mock_instance = MagicMock()
            mock_tools = [MagicMock(spec=BaseTool), MagicMock(spec=BaseTool)]
            mock_instance.get_tools.return_value = mock_tools
            mock_toolkit_class.return_value = mock_instance

            tool = factory.create_tool_from_toolbox("test_toolkit", user_args)

            # Ensure the correct class was resolved
            mock_resolver.assert_called_once_with("TestToolkit", module_name="mock_module")

            # Ensure _check_invalid_args was called
            mock_check_invalid.assert_called_once()

            # Ensure the tool was initialized with the correct merged args
            mock_toolkit_class.assert_called_once_with(param1="value1", param2="user_value", param3="extra_value")

            assert tool == mock_tools
            mock_instance.get_tools.assert_called_once()

    def test_create_toolbox_with_toolkit_class_method(self, factory):
        """Test the toolkit that instantiates with class method"""
        factory.toolbox_infos = {
            "method_toolkit": {
                "class": "mock_package.mock_module.TestToolkit",
                "args": {
                    "param1": "value1",
                    "param2": "value2"
                }
            }
        }

        # Mock user-provided arguments
        user_args = {"param2": "user_value", "param3": "extra_value"}

        with patch(RESOLVER_PATH) as mock_resolver, patch(VALIDATIOR_PATH) as mock_check_invalid:
            # Mock the toolkit class
            mock_toolkit_class = MagicMock()
            mock_resolver.return_value = mock_toolkit_class

            # Mock the class method
            mock_toolkit_instance = MagicMock()
            mock_toolkit_class.from_tool_api_wrapper.return_value = mock_toolkit_instance

            # Mock get_tools() returning a list of tools
            mock_tool_1 = MagicMock(spec=BaseTool)
            mock_tool_2 = MagicMock(spec=BaseTool)
            mock_toolkit_instance.get_tools.return_value = [mock_tool_1, mock_tool_2]

            # Call the factory method
            tools = factory.create_tool_from_toolbox("method_toolkit", user_args)

            # Ensure the correct method was called instead of the constructor
            mock_toolkit_class.from_tool_api_wrapper.assert_called_once_with(
                param1="value1", param2="user_value", param3="extra_value")

            # Ensure _check_invalid_args was called
            mock_check_invalid.assert_called_once()

            # Ensure get_tools() was called
            mock_toolkit_instance.get_tools.assert_called_once()

            # Ensure the returned tools match the mocked tools
            assert tools == [mock_tool_1, mock_tool_2]
