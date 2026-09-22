
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
    Unit tests for McpManifestDictConfigFilter: the "mcp" default, the
    mcp-implies-public rule, and the handling of the optional "mcp_name" key.
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
        self.assertFalse(filtered.get("mcp"))

    def test_absent_mcp_defaults_to_false(self) -> None:
        """
        When "mcp" is not in the entry it is filled in as False and "public" is left alone.
        """
        basis_config: Dict[str, Any] = {StorageClass.PUBLIC: False}
        filtered: Dict[str, Any] = self.make_filter().filter_config(basis_config)
        self.assertIn("mcp", filtered)
        self.assertFalse(filtered.get("mcp"))
        self.assertFalse(filtered.get(StorageClass.PUBLIC))

    def test_mcp_true_implies_public(self) -> None:
        """
        An MCP tool has to be discoverable, so "mcp": true forces "public": true.
        """
        basis_config: Dict[str, Any] = {"mcp": True, StorageClass.PUBLIC: False}
        filtered: Dict[str, Any] = self.make_filter().filter_config(basis_config)
        self.assertTrue(filtered.get("mcp"))
        self.assertTrue(filtered.get(StorageClass.PUBLIC))

    def test_mcp_false_leaves_public_alone(self) -> None:
        """
        "mcp": false does not touch "public".
        """
        basis_config: Dict[str, Any] = {"mcp": False, StorageClass.PUBLIC: False}
        filtered: Dict[str, Any] = self.make_filter().filter_config(basis_config)
        self.assertFalse(filtered.get("mcp"))
        self.assertFalse(filtered.get(StorageClass.PUBLIC))

    def test_valid_mcp_name_implies_mcp_and_public_and_is_kept(self) -> None:
        """
        A non-empty string "mcp_name" turns "mcp" and "public" on and survives the filter,
        so the restorer can pick it up as the name to advertise.
        """
        basis_config: Dict[str, Any] = {"mcp_name": "calc"}
        filtered: Dict[str, Any] = self.make_filter().filter_config(basis_config)
        self.assertTrue(filtered.get("mcp"))
        self.assertTrue(filtered.get(StorageClass.PUBLIC))
        self.assertEqual("calc", filtered.get("mcp_name"))

    def test_mcp_name_is_not_validated_here(self) -> None:
        """
        The filter does not judge the shape of the name; that happens once, in the restorer,
        with the final derived value. A slash spelling therefore passes through untouched.
        """
        basis_config: Dict[str, Any] = {"mcp_name": "deep/math_guy"}
        with self.assertNoLogs(self.LOGGER_NAME, level=WARNING):
            filtered: Dict[str, Any] = self.make_filter().filter_config(basis_config)
        self.assertEqual("deep/math_guy", filtered.get("mcp_name"))

    def test_non_string_mcp_name_is_removed_with_warning(self) -> None:
        """
        A non-string "mcp_name" is dropped and warned about, naming the manifest and network,
        and does not switch "mcp" on by itself.
        """
        basis_config: Dict[str, Any] = {"mcp_name": 42}
        with self.assertLogs(self.LOGGER_NAME, level=WARNING) as captured:
            filtered: Dict[str, Any] = self.make_filter().filter_config(basis_config)
        self.assertNotIn("mcp_name", filtered)
        self.assertFalse(filtered.get("mcp"))
        self.assertEqual(1, len(captured.output))
        self.assertIn("manifest.hocon", captured.output[0])
        self.assertIn("deep/math_guy", captured.output[0])
        self.assertIn("42", captured.output[0])

    def test_empty_mcp_name_is_removed_with_warning(self) -> None:
        """
        An empty string is not a usable tool name and is treated like a non-string.
        """
        basis_config: Dict[str, Any] = {"mcp_name": ""}
        with self.assertLogs(self.LOGGER_NAME, level=WARNING):
            filtered: Dict[str, Any] = self.make_filter().filter_config(basis_config)
        self.assertNotIn("mcp_name", filtered)
        self.assertFalse(filtered.get("mcp"))

    def test_explicit_mcp_false_beats_mcp_name_with_warning(self) -> None:
        """
        An entry that opts out with "mcp": false keeps that choice even when it also names
        an "mcp_name": the network is not switched on, and the ineffective name is warned about.
        """
        basis_config: Dict[str, Any] = {"mcp": False, "mcp_name": "solo"}
        with self.assertLogs(self.LOGGER_NAME, level=WARNING) as captured:
            filtered: Dict[str, Any] = self.make_filter().filter_config(basis_config)
        self.assertFalse(filtered.get("mcp"))
        self.assertFalse(filtered.get(StorageClass.PUBLIC))
        self.assertEqual("solo", filtered.get("mcp_name"))
        self.assertEqual(1, len(captured.output))
        self.assertIn("solo", captured.output[0])
        self.assertIn("deep/math_guy", captured.output[0])

    def test_bad_mcp_name_does_not_undo_explicit_mcp_true(self) -> None:
        """
        Dropping a bad "mcp_name" only removes that key; an explicit "mcp": true still stands.
        """
        basis_config: Dict[str, Any] = {"mcp": True, "mcp_name": None}
        with self.assertLogs(self.LOGGER_NAME, level=WARNING):
            filtered: Dict[str, Any] = self.make_filter().filter_config(basis_config)
        self.assertNotIn("mcp_name", filtered)
        self.assertTrue(filtered.get("mcp"))
        self.assertTrue(filtered.get(StorageClass.PUBLIC))
