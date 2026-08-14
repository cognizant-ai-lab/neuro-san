
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

from unittest.mock import patch, MagicMock

import pytest

from langchain_core.tools.base import BaseTool
from langchain_core.tools.base import BaseToolkit

from neuro_san.internals.run_context.langchain.toolbox.toolbox_factory import ToolboxFactory

FIXTURE_MODULE = "tests.neuro_san.internals.run_context.langchain.toolbox.real_tool_fixture"

RESOLVER_PATH = "leaf_common.resolution.resolver.Resolver.resolve_class_in_module"
VALIDATIOR_PATH = (
    "neuro_san.internals.run_context.langchain.util.argument_validator."
    "ArgumentValidator.check_invalid_args"
)


class TestToolboxFactory:
    """Simplified test suite for ToolboxFactory."""

    @pytest.fixture
    def factory(self):
        """Fixture to provide a fresh instance of ToolboxFactory."""
        return ToolboxFactory()

    def test_load_only_loads_once(self, factory):
        """Test that load() reads hocon files on the first call only."""
        # Keep the test hermetic: no user toolbox info file from the environment.
        factory.toolbox_info_file = None
        restorer_path = (
            "neuro_san.internals.run_context.langchain.toolbox."
            "toolbox_factory.ToolboxInfoRestorer"
        )
        infos = {"some_tool": {"class": "mock_package.mock_module.SomeTool"}}
        with patch(restorer_path) as mock_restorer:
            mock_restorer.return_value.restore.return_value = infos

            assert not factory.loaded
            factory.load()
            assert factory.loaded
            assert factory.toolbox_infos == infos

            # A second load() must be a no-op: no further file reads,
            # and the previously loaded infos are kept.
            factory.load()
            mock_restorer.return_value.restore.assert_called_once()
            assert factory.toolbox_infos == infos

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
            mock_instance.name = MagicMock(spec=str)
            mock_instance.tags = MagicMock(spec=list)
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

    def test_create_toolbox_with_removed_tool_gives_migration_error(self, factory):
        """Test that a reference to a removed requests_* tool explains the removal
        and how to migrate, rather than raising a generic 'not defined' error."""
        factory.toolbox_infos = {}

        with pytest.raises(ValueError, match="deprecated langchain-community") as exc_info:
            factory.create_tool_from_toolbox("requests_get", {})
        assert "AGENT_TOOLBOX_INFO_FILE" in str(exc_info.value)

    def test_create_toolbox_with_partial_override_of_removed_tool(self, factory):
        """Test that a class-less entry for a removed tool also gets the migration
        error. A user toolbox file that overrides only the args of a removed
        entry used to inherit 'class' from the bundled default via the overlay;
        it should not die on a generic missing-'class' message."""
        factory.toolbox_infos = {
            "requests_get": {"args": {"headers": {"Authorization": "Bearer token"}}},
        }

        with pytest.raises(ValueError, match="deprecated langchain-community"):
            factory.create_tool_from_toolbox("requests_get", {})

    def test_create_toolbox_missing_class_names_the_tool(self, factory):
        """Test that the missing-'class' error names the offending tool."""
        factory.toolbox_infos = {
            "my_tool": {"args": {"param": "value"}},
        }

        with pytest.raises(ValueError, match="Tool 'my_tool' is missing required key: 'class'"):
            factory.create_tool_from_toolbox("my_tool", {})

    def test_empty_tool_entry_reports_missing_class(self, factory):
        """Test that an empty (but present) tool entry is reported as missing
        'class' rather than as not defined, from both toolbox entry points."""
        factory.toolbox_infos = {
            "empty_tool": {},
        }

        with pytest.raises(ValueError, match="Tool 'empty_tool' is missing required key: 'class'"):
            factory.create_tool_from_toolbox("empty_tool", {})

        with pytest.raises(ValueError, match="Tool 'empty_tool' is missing required key: 'class'"):
            factory.get_shared_coded_tool_class("empty_tool")

    def test_create_toolbox_with_unknown_tool_names_sources(self, factory):
        """Test that an unknown tool name reports the searched sources by name.
        Previously the message rendered 'not defined in None' when no user
        toolbox info file was configured."""
        factory.toolbox_infos = {}

        factory.toolbox_info_file = None
        with pytest.raises(ValueError, match="not defined in the default toolbox info file."):
            factory.create_tool_from_toolbox("no_such_tool", {})

        factory.toolbox_info_file = "/path/to/user_toolbox.hocon"
        with pytest.raises(ValueError, match="or in /path/to/user_toolbox.hocon"):
            factory.create_tool_from_toolbox("no_such_tool", {})

    def test_create_toolbox_real_tool_unmocked(self, factory):
        """Test tool creation with no mocks: a real BaseTool subclass and a real
        nested wrapper class are resolved from their class paths, validated,
        instantiated, and tagged — the same path an operator's toolbox info
        file entry takes."""
        factory.toolbox_infos = {
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

        tool = factory.create_tool_from_toolbox("real_tool", user_args={"max_results": 7}, agent_name="my_agent")

        assert isinstance(tool, BaseTool)
        assert tool.name == "my_agent"
        assert tool.tags == ["langchain_tool"]
        # user_args override the toolbox-file args; nested wrapper args survive
        assert tool.max_results == 7
        assert tool.api_wrapper.timeout == 30

    def test_langchain_community_class_logs_sunset_warning(self, factory, caplog):
        """Test that a tool whose class comes from langchain-community logs the
        sunset warning on creation."""
        factory.toolbox_infos = {
            "community_tool": {"class": "langchain_community.some_module.SomeTool"},
        }

        with patch(RESOLVER_PATH) as mock_resolver, patch(VALIDATIOR_PATH):
            mock_tool_class = MagicMock(spec=BaseTool)
            mock_resolver.return_value = mock_tool_class

            mock_instance = MagicMock(spec=BaseTool)
            mock_instance.name = MagicMock(spec=str)
            mock_instance.tags = MagicMock(spec=list)
            mock_tool_class.return_value = mock_instance

            with caplog.at_level(logging.WARNING):
                factory.create_tool_from_toolbox("community_tool", {})

        assert "langchain-community" in caplog.text
        assert "sunset" in caplog.text

    def test_get_shared_coded_tool_class_unknown_tool_raises(self, factory):
        """Test that unknown and removed tool names raise the same clear
        ValueErrors as create_tool_from_toolbox(), instead of crashing with
        AttributeError on the missing toolbox entry."""
        factory.toolbox_infos = {
            "known_tool": {"class": "some_module.SomeCodedTool"},
        }
        factory.toolbox_info_file = None

        assert factory.get_shared_coded_tool_class("known_tool") == "some_module.SomeCodedTool"

        with pytest.raises(ValueError, match="not defined in the default toolbox info file."):
            factory.get_shared_coded_tool_class("no_such_tool")

        with pytest.raises(ValueError, match="deprecated langchain-community"):
            factory.get_shared_coded_tool_class("requests_get")

    @pytest.mark.parametrize("bad_class", [None, 123, ""])
    def test_create_toolbox_with_invalid_class_value(self, factory, bad_class):
        """Test that a non-string or empty 'class' value raises a clear ValueError
        from both toolbox entry points."""
        factory.toolbox_infos = {
            "bad_tool": {
                "class": bad_class
            }
        }

        with pytest.raises(ValueError, match="must be a non-empty string"):
            factory.create_tool_from_toolbox("bad_tool", {})

        with pytest.raises(ValueError, match="must be a non-empty string"):
            factory.get_shared_coded_tool_class("bad_tool")

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
            mock_tool_1 = MagicMock(spec=BaseTool)
            mock_tool_1.name = MagicMock(spec=str)
            mock_tool_1.tags = MagicMock(spec=list)
            mock_tool_2 = MagicMock(spec=BaseTool)
            mock_tool_2.name = MagicMock(spec=str)
            mock_tool_2.tags = MagicMock(spec=list)
            mock_tools = [mock_tool_1, mock_tool_2]
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
            mock_tool_1.name = MagicMock(spec=str)
            mock_tool_1.tags = MagicMock(spec=list)
            mock_tool_2 = MagicMock(spec=BaseTool)
            mock_tool_2.name = MagicMock(spec=str)
            mock_tool_2.tags = MagicMock(spec=list)
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
