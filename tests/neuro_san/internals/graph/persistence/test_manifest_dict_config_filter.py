
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

from neuro_san.internals.graph.persistence.manifest_dict_config_filter import ManifestDictConfigFilter
from neuro_san.internals.interfaces.storage_class import StorageClass


class TestManifestDictConfigFilter(TestCase):
    """
    Unit tests for ManifestDictConfigFilter's hand-off of dictionary entries to the
    per-entry filter chain: the manifest file and the entry key must reach
    McpManifestDictConfigFilter so that its warnings say which entry they are about,
    and an "mcp" dictionary in an entry must come out the other end as an MCP-enabled,
    public entry.
    """

    MCP_LOGGER_NAME: str = "McpManifestDictConfigFilter"
    MANIFEST_FILE: str = "manifest.hocon"
    ENTRY_KEY: str = "deep/math_guy.hocon"

    def test_bad_name_warning_names_manifest_and_entry(self) -> None:
        """
        A non-string "name" in the "mcp" dictionary is dropped by the chain with a warning
        that names both the manifest file and the entry, which only works if the chain was
        given them.
        """
        config_filter = ManifestDictConfigFilter(self.MANIFEST_FILE)
        basis_config: Dict[str, Any] = {self.ENTRY_KEY: {"serve": True, "mcp": {"name": 42}}}
        with self.assertLogs(self.MCP_LOGGER_NAME, level=WARNING) as captured:
            filtered: Dict[str, Dict[str, Any]] = config_filter.filter_config(basis_config)
        self.assertIsNone(filtered[self.ENTRY_KEY]["mcp"].get("name"))
        self.assertEqual(1, len(captured.output))
        self.assertIn(self.MANIFEST_FILE, captured.output[0])
        self.assertIn(self.ENTRY_KEY, captured.output[0])

    def test_dict_entry_with_name_comes_out_mcp_and_public(self) -> None:
        """
        A dictionary entry with "mcp": { "name": ... } is switched on as an MCP tool and made
        public by the chain, and keeps the name for RegistryManifestRestorer to use.
        """
        config_filter = ManifestDictConfigFilter(self.MANIFEST_FILE)
        basis_config: Dict[str, Any] = {self.ENTRY_KEY: {"serve": True, "mcp": {"name": "calculator"}}}
        filtered: Dict[str, Dict[str, Any]] = config_filter.filter_config(basis_config)
        entry: Dict[str, Any] = filtered[self.ENTRY_KEY]
        self.assertEqual({"enable": True, "name": "calculator"}, entry.get("mcp"))
        self.assertTrue(entry.get(StorageClass.PUBLIC))

    def test_bare_true_entry_comes_out_mcp_enabled(self) -> None:
        """
        The traditional `"x.hocon": true` entry expands to served, public and MCP-enabled,
        with the "mcp" template boolean normalised to the settings dictionary.
        """
        config_filter = ManifestDictConfigFilter(self.MANIFEST_FILE)
        filtered: Dict[str, Dict[str, Any]] = config_filter.filter_config({self.ENTRY_KEY: True})
        entry: Dict[str, Any] = filtered[self.ENTRY_KEY]
        self.assertTrue(entry.get("serve"))
        self.assertTrue(entry.get(StorageClass.PUBLIC))
        self.assertEqual({"enable": True, "name": None}, entry.get("mcp"))
