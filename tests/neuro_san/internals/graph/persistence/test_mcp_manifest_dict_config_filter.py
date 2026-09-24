
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

from logging import WARNING
from unittest import TestCase

from neuro_san.internals.graph.persistence.mcp_manifest_dict_config_filter import McpManifestDictConfigFilter
from neuro_san.internals.interfaces.storage_class import StorageClass


class TestMcpManifestDictConfigFilter(TestCase):
    """
    Unit tests for McpManifestDictConfigFilter: every form of the "mcp" manifest key
    (absent, boolean, dictionary) comes out as the {"enable", "name"} settings dictionary,
    an enabled tool implies "public", and bad values are dropped with a warning.
    """

    # The filter logs under its class name, mirroring the other manifest filters.
    LOGGER_NAME: str = "McpManifestDictConfigFilter"

    def make_filter(self) -> McpManifestDictConfigFilter:
        """
        Builds a filter with the same logging context the filter chain supplies.

        :return: A McpManifestDictConfigFilter for a fake manifest file and network.
        """
        return McpManifestDictConfigFilter("manifest.hocon", "deep/math_guy")

    def test_no_arg_constructor_still_works(self) -> None:
        """
        The constructor arguments are optional so existing no-arg construction keeps working.
        """
        config_filter = McpManifestDictConfigFilter()
        filtered: Dict[str, Any] = config_filter.filter_config({})
        self.assertEqual({"enable": False, "name": None}, filtered.get("mcp"))

    def test_absent_mcp_is_disabled_and_leaves_public_alone(self) -> None:
        """
        When "mcp" is not in the entry it becomes a disabled settings dictionary
        and "public" is left alone.
        """
        basis_config: Dict[str, Any] = {StorageClass.PUBLIC: False}
        # Absent is the normal case for dictionary entries, so it must stay silent.
        with self.assertNoLogs(self.LOGGER_NAME, level=WARNING):
            filtered: Dict[str, Any] = self.make_filter().filter_config(basis_config)
        self.assertEqual({"enable": False, "name": None}, filtered.get("mcp"))
        self.assertFalse(filtered.get(StorageClass.PUBLIC))

    def test_mcp_true_is_enabled_with_derived_name_and_implies_public(self) -> None:
        """
        The plain boolean form: "mcp": true enables the tool, leaves the name to be
        derived, and forces "public": true since an MCP tool has to be discoverable.
        """
        basis_config: Dict[str, Any] = {"mcp": True, StorageClass.PUBLIC: False}
        filtered: Dict[str, Any] = self.make_filter().filter_config(basis_config)
        self.assertEqual({"enable": True, "name": None}, filtered.get("mcp"))
        self.assertTrue(filtered.get(StorageClass.PUBLIC))

    def test_mcp_false_is_disabled_and_leaves_public_alone(self) -> None:
        """
        "mcp": false is the same as absent and does not touch "public".
        """
        basis_config: Dict[str, Any] = {"mcp": False, StorageClass.PUBLIC: False}
        filtered: Dict[str, Any] = self.make_filter().filter_config(basis_config)
        self.assertEqual({"enable": False, "name": None}, filtered.get("mcp"))
        self.assertFalse(filtered.get(StorageClass.PUBLIC))

    def test_dictionary_with_name_is_enabled_and_public(self) -> None:
        """
        Giving the dictionary switches the tool on without saying "enable", keeps the
        name for the restorer to advertise, and implies "public".
        """
        basis_config: Dict[str, Any] = {"mcp": {"name": "calc"}, StorageClass.PUBLIC: False}
        filtered: Dict[str, Any] = self.make_filter().filter_config(basis_config)
        self.assertEqual({"enable": True, "name": "calc"}, filtered.get("mcp"))
        self.assertTrue(filtered.get(StorageClass.PUBLIC))

    def test_empty_dictionary_is_enabled_with_derived_name(self) -> None:
        """
        "mcp": {} means the same as "mcp": true, and a missing name is not worth a warning.
        """
        with self.assertNoLogs(self.LOGGER_NAME, level=WARNING):
            filtered: Dict[str, Any] = self.make_filter().filter_config({"mcp": {}})
        self.assertEqual({"enable": True, "name": None}, filtered.get("mcp"))
        self.assertTrue(filtered.get(StorageClass.PUBLIC))

    def test_enable_false_keeps_name_and_leaves_public_alone(self) -> None:
        """
        "enable": false is an explicit opt-out: the network is not an MCP tool, "public"
        is untouched, and the name stays in the settings for when it is switched back on.
        """
        basis_config: Dict[str, Any] = {"mcp": {"enable": False, "name": "calc"}, StorageClass.PUBLIC: False}
        with self.assertNoLogs(self.LOGGER_NAME, level=WARNING):
            filtered: Dict[str, Any] = self.make_filter().filter_config(basis_config)
        self.assertEqual({"enable": False, "name": "calc"}, filtered.get("mcp"))
        self.assertFalse(filtered.get(StorageClass.PUBLIC))

    def test_name_is_not_validated_here(self) -> None:
        """
        The filter does not judge the shape of the name; that happens once, in the restorer,
        with the final derived value. A slash spelling therefore passes through untouched.
        """
        basis_config: Dict[str, Any] = {"mcp": {"name": "deep/math_guy"}}
        with self.assertNoLogs(self.LOGGER_NAME, level=WARNING):
            filtered: Dict[str, Any] = self.make_filter().filter_config(basis_config)
        self.assertEqual("deep/math_guy", filtered["mcp"].get("name"))

    def test_non_string_name_is_dropped_with_warning(self) -> None:
        """
        A non-string "name" is dropped and warned about, naming the manifest and network;
        the tool itself stays enabled so its name gets derived instead.
        """
        basis_config: Dict[str, Any] = {"mcp": {"name": 42}}
        with self.assertLogs(self.LOGGER_NAME, level=WARNING) as captured:
            filtered: Dict[str, Any] = self.make_filter().filter_config(basis_config)
        self.assertEqual({"enable": True, "name": None}, filtered.get("mcp"))
        self.assertEqual(1, len(captured.output))
        self.assertIn("manifest.hocon", captured.output[0])
        self.assertIn("deep/math_guy", captured.output[0])
        self.assertIn("42", captured.output[0])

    def test_empty_name_is_dropped_with_warning(self) -> None:
        """
        An empty string is not a usable tool name and is treated like a non-string.
        """
        basis_config: Dict[str, Any] = {"mcp": {"name": ""}}
        with self.assertLogs(self.LOGGER_NAME, level=WARNING):
            filtered: Dict[str, Any] = self.make_filter().filter_config(basis_config)
        self.assertIsNone(filtered["mcp"].get("name"))
        self.assertTrue(filtered["mcp"].get("enable"))

    def test_non_boolean_enable_is_read_by_truthiness_with_warning(self) -> None:
        """
        An "enable" that is not a boolean is warned about and read for its truth value.
        """
        basis_config: Dict[str, Any] = {"mcp": {"enable": "yes"}}
        with self.assertLogs(self.LOGGER_NAME, level=WARNING) as captured:
            filtered: Dict[str, Any] = self.make_filter().filter_config(basis_config)
        self.assertIs(True, filtered["mcp"].get("enable"))
        self.assertIn("'yes'", captured.output[0])

    def test_falsy_non_boolean_enable_switches_the_tool_off(self) -> None:
        """
        The truth value really is read: a falsy non-boolean such as 0 disables the tool
        and therefore does not imply "public".
        """
        basis_config: Dict[str, Any] = {"mcp": {"enable": 0}, StorageClass.PUBLIC: False}
        with self.assertLogs(self.LOGGER_NAME, level=WARNING):
            filtered: Dict[str, Any] = self.make_filter().filter_config(basis_config)
        self.assertIs(False, filtered["mcp"].get("enable"))
        self.assertFalse(filtered.get(StorageClass.PUBLIC))

    def test_unknown_keys_in_dictionary_are_kept(self) -> None:
        """
        Extra keys survive the filter, so MCP settings can grow without changing it.
        """
        basis_config: Dict[str, Any] = {"mcp": {"name": "calc", "future": 1}}
        filtered: Dict[str, Any] = self.make_filter().filter_config(basis_config)
        self.assertEqual(1, filtered["mcp"].get("future"))
        self.assertEqual("calc", filtered["mcp"].get("name"))

    def test_other_value_types_are_disabled_with_warning(self) -> None:
        """
        A value that is neither a boolean nor a dictionary (a bare string, say) is
        warned about and treated as false.
        """
        basis_config: Dict[str, Any] = {"mcp": "calc", StorageClass.PUBLIC: False}
        with self.assertLogs(self.LOGGER_NAME, level=WARNING) as captured:
            filtered: Dict[str, Any] = self.make_filter().filter_config(basis_config)
        self.assertEqual({"enable": False, "name": None}, filtered.get("mcp"))
        self.assertFalse(filtered.get(StorageClass.PUBLIC))
        self.assertIn("'calc'", captured.output[0])

    def test_input_dictionary_is_not_shared_with_output(self) -> None:
        """
        The settings dictionary is a fresh object, so a manifest dictionary reused by the
        caller is not mutated behind its back.
        """
        given: Dict[str, Any] = {"name": "calc"}
        filtered: Dict[str, Any] = self.make_filter().filter_config({"mcp": given})
        self.assertIsNot(given, filtered.get("mcp"))
        self.assertEqual({"name": "calc"}, given)
