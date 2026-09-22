
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
from typing import List

from logging import ERROR
from logging import WARNING
from os import makedirs
from os.path import dirname
from os.path import join
from tempfile import TemporaryDirectory
from unittest import TestCase

from neuro_san.internals.graph.persistence.agent_filetree_mapper import AgentFileTreeMapper
from neuro_san.internals.graph.persistence.registry_manifest_restorer import RegistryManifestRestorer
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.storage_class import StorageClass
from neuro_san.internals.validation.network.manifest_network_validator import ManifestNetworkValidator


# One test per rule of the derivation, collision and manifest-key handling adds up.
# pylint: disable=too-many-public-methods
class TestRegistryManifestRestorer(TestCase):
    """
    Unit tests for the MCP tool naming done by RegistryManifestRestorer:
    deriving the advertised tool name for one network in process_one_agent_network(),
    and resolving networks that would advertise the same tool name.
    """

    # process_one_agent_network() and derive_mcp_tool_name() log through
    # getLogger(__name__) of the restorer module ...
    MODULE_LOGGER: str = "neuro_san.internals.graph.persistence.registry_manifest_restorer"
    # ... while instance methods log through getLogger(class name).
    INSTANCE_LOGGER: str = "RegistryManifestRestorer"

    NESTED_NAME: str = "deep/math_guy"
    NESTED_TOOL_NAME: str = "deep__math_guy"
    TOP_NAME: str = "math_guy"

    def make_agent_network(self, network_name: str) -> AgentNetwork:
        """
        Builds a minimal, valid AgentNetwork with a single front man.

        :param network_name: The network name to give it
        :return: An AgentNetwork that is not (yet) an MCP tool
        """
        config: Dict[str, Any] = {
            "tools": [
                {"name": "front", "function": {"description": "x"}}
            ]
        }
        return AgentNetwork(config, network_name)

    def process(self, agent_network: AgentNetwork, manifest_dict: Dict[str, Any]) -> AgentNetwork:
        """
        Runs process_one_agent_network() for a usable network the way read_one_agent_network() does,
        with a real validator and the default file tree mapper.

        :param agent_network: The restored AgentNetwork to process
        :param manifest_dict: The already-filtered manifest entry for it
        :return: Whatever process_one_agent_network() returns
        """
        network_name: str = agent_network.get_network_name()
        # AgentFileTreeMapper maps "<network_name>.hocon" straight back to network_name.
        agent_filepath: str = f"{network_name}.hocon"
        validator = ManifestNetworkValidator([f"/{network_name}"], network_name=network_name)
        return RegistryManifestRestorer.process_one_agent_network(
            agent_network, True, agent_filepath, "manifest.hocon", network_name,
            manifest_dict, validator, AgentFileTreeMapper())

    def test_mcp_true_derives_provider_safe_tool_name(self) -> None:
        """
        With "mcp": true and no "mcp_name", a nested network is advertised with "/" turned into "__".
        """
        agent_network: AgentNetwork = self.make_agent_network(self.NESTED_NAME)
        result: AgentNetwork = self.process(agent_network, {"serve": True, "mcp": True})
        self.assertIs(agent_network, result)
        self.assertTrue(result.is_mcp_tool())
        self.assertEqual(self.NESTED_TOOL_NAME, result.get_mcp_tool_name())
        # The internal key is untouched.
        self.assertEqual(self.NESTED_NAME, result.get_network_name())

    def test_top_level_network_keeps_its_name(self) -> None:
        """
        A top-level network has no "/" so its tool name is the network name itself.
        """
        agent_network: AgentNetwork = self.make_agent_network(self.TOP_NAME)
        result: AgentNetwork = self.process(agent_network, {"serve": True, "mcp": True})
        self.assertEqual(self.TOP_NAME, result.get_mcp_tool_name())

    def test_mcp_name_overrides_derivation(self) -> None:
        """
        An explicit "mcp_name" wins over the derived name.
        """
        agent_network: AgentNetwork = self.make_agent_network(self.NESTED_NAME)
        result: AgentNetwork = self.process(agent_network, {"serve": True, "mcp": True, "mcp_name": "calc"})
        self.assertTrue(result.is_mcp_tool())
        self.assertEqual("calc", result.get_mcp_tool_name())

    def test_mcp_false_is_not_an_mcp_tool(self) -> None:
        """
        With "mcp": false the network is served but not exposed over MCP.
        """
        agent_network: AgentNetwork = self.make_agent_network(self.NESTED_NAME)
        result: AgentNetwork = self.process(agent_network, {"serve": True, "mcp": False})
        self.assertIs(agent_network, result)
        self.assertFalse(result.is_mcp_tool())
        self.assertIsNone(result.get_mcp_tool_name())

    def test_invalid_tool_name_warns_but_is_still_exposed(self) -> None:
        """
        A tool name outside the provider-safe pattern is warned about at startup
        but the network is still exposed, so lenient clients keep working.
        """
        agent_network: AgentNetwork = self.make_agent_network(self.NESTED_NAME)
        manifest_dict: Dict[str, Any] = {"serve": True, "mcp": True, "mcp_name": "deep/math_guy"}
        with self.assertLogs(self.MODULE_LOGGER, level=WARNING) as captured:
            result: AgentNetwork = self.process(agent_network, manifest_dict)
        self.assertTrue(result.is_mcp_tool())
        self.assertEqual("deep/math_guy", result.get_mcp_tool_name())
        self.assertEqual(1, len(captured.output))
        self.assertIn("deep/math_guy", captured.output[0])
        self.assertIn("OpenAI", captured.output[0])

    def test_long_derived_tool_name_warns_about_openai_cap(self) -> None:
        """
        A derived name longer than 64 characters is valid for Anthropic but not OpenAI,
        so it is warned about and still exposed.
        """
        long_name: str = "deep/" + ("x" * 70)
        agent_network: AgentNetwork = self.make_agent_network(long_name)
        with self.assertLogs(self.MODULE_LOGGER, level=WARNING) as captured:
            result: AgentNetwork = self.process(agent_network, {"serve": True, "mcp": True})
        self.assertTrue(result.is_mcp_tool())
        self.assertEqual("deep__" + ("x" * 70), result.get_mcp_tool_name())
        self.assertEqual(1, len(captured.output))
        self.assertIn("64", captured.output[0])

    def test_valid_derived_name_logs_no_warning(self) -> None:
        """
        The common case, a short derived name, produces no warning at all.
        """
        agent_network: AgentNetwork = self.make_agent_network(self.NESTED_NAME)
        with self.assertNoLogs(self.MODULE_LOGGER, level=WARNING):
            self.process(agent_network, {"serve": True, "mcp": True})

    def test_derive_mcp_tool_name_ignores_empty_mcp_name(self) -> None:
        """
        An empty "mcp_name" (which the filter normally strips) falls back to derivation.
        """
        tool_name: str = RegistryManifestRestorer.derive_mcp_tool_name(self.NESTED_NAME, {"mcp_name": ""})
        self.assertEqual(self.NESTED_TOOL_NAME, tool_name)

    def make_restorer(self) -> RegistryManifestRestorer:
        """
        Builds a restorer that never touches the file system.

        :return: A RegistryManifestRestorer over a manifest list that is never read
        """
        return RegistryManifestRestorer(manifest_files=["manifest.hocon"])

    def test_resolve_collisions_keeps_unmangled_network(self) -> None:
        """
        When a renamed network ("deep/math_guy" with mcp_name "math_guy") collides with a network
        literally named "math_guy", the network whose own name is the tool name keeps it,
        even though it sorts after the contender, and the other loses MCP exposure with an error log.
        """
        top: AgentNetwork = self.make_agent_network(self.TOP_NAME)
        top.set_as_mcp_tool(self.TOP_NAME)
        nested: AgentNetwork = self.make_agent_network(self.NESTED_NAME)
        nested.set_as_mcp_tool(self.TOP_NAME)
        all_agent_networks: Dict[str, Dict[str, AgentNetwork]] = {
            StorageClass.PUBLIC: {self.NESTED_NAME: nested, self.TOP_NAME: top},
            StorageClass.PROTECTED: {}
        }

        with self.assertLogs(self.INSTANCE_LOGGER, level=ERROR) as captured:
            self.make_restorer().resolve_mcp_tool_name_collisions(all_agent_networks)

        self.assertTrue(top.is_mcp_tool())
        self.assertEqual(self.TOP_NAME, top.get_mcp_tool_name())
        self.assertFalse(nested.is_mcp_tool())
        self.assertIsNone(nested.get_mcp_tool_name())
        # The loser is still in storage; only its MCP exposure is withdrawn.
        self.assertIs(nested, all_agent_networks[StorageClass.PUBLIC][self.NESTED_NAME])
        self.assertEqual(1, len(captured.output))
        self.assertIn(self.NESTED_NAME, captured.output[0])
        self.assertIn(self.TOP_NAME, captured.output[0])

    def test_resolve_collisions_keeps_first_seen_when_neither_is_unmangled(self) -> None:
        """
        Two networks with the same explicit mcp_name: the first in sorted network-name order keeps it.
        """
        alpha: AgentNetwork = self.make_agent_network("alpha")
        alpha.set_as_mcp_tool("calc")
        beta: AgentNetwork = self.make_agent_network("beta")
        beta.set_as_mcp_tool("calc")
        # Insert in reverse order to show that dict order does not decide.
        all_agent_networks: Dict[str, Dict[str, AgentNetwork]] = {
            StorageClass.PUBLIC: {"beta": beta, "alpha": alpha}
        }

        with self.assertLogs(self.INSTANCE_LOGGER, level=ERROR):
            self.make_restorer().resolve_mcp_tool_name_collisions(all_agent_networks)

        self.assertTrue(alpha.is_mcp_tool())
        self.assertEqual("calc", alpha.get_mcp_tool_name())
        self.assertFalse(beta.is_mcp_tool())

    def test_resolve_collisions_mangled_path_vs_literal_name(self) -> None:
        """
        The motivating case: "a/b" derives to "a__b", which collides with a network literally
        named "a__b". The literal one keeps the name.
        """
        path_network: AgentNetwork = self.make_agent_network("a/b")
        path_network.set_as_mcp_tool("a__b")
        literal_network: AgentNetwork = self.make_agent_network("a__b")
        literal_network.set_as_mcp_tool("a__b")
        all_agent_networks: Dict[str, Dict[str, AgentNetwork]] = {
            StorageClass.PUBLIC: {"a/b": path_network, "a__b": literal_network}
        }

        with self.assertLogs(self.INSTANCE_LOGGER, level=ERROR):
            self.make_restorer().resolve_mcp_tool_name_collisions(all_agent_networks)

        self.assertTrue(literal_network.is_mcp_tool())
        self.assertFalse(path_network.is_mcp_tool())

    def test_resolve_collisions_reserves_own_name_of_aliased_network(self) -> None:
        """
        "a/b" derives to "a__b" while the network literally named "a__b" is advertised
        under the alias "other". The two advertised names differ, but "a__b" is still
        how a client that has not seen tools/list addresses the literal network, so
        "a/b" may not take it: the literal network keeps its alias, "a/b" loses MCP exposure.
        "a/b" sorts first, so its claim is the earlier one.
        """
        path_network: AgentNetwork = self.make_agent_network("a/b")
        path_network.set_as_mcp_tool("a__b")
        literal_network: AgentNetwork = self.make_agent_network("a__b")
        literal_network.set_as_mcp_tool("other")
        all_agent_networks: Dict[str, Dict[str, AgentNetwork]] = {
            StorageClass.PUBLIC: {"a/b": path_network, "a__b": literal_network}
        }

        with self.assertLogs(self.INSTANCE_LOGGER, level=ERROR) as captured:
            self.make_restorer().resolve_mcp_tool_name_collisions(all_agent_networks)

        self.assertTrue(literal_network.is_mcp_tool())
        self.assertEqual("other", literal_network.get_mcp_tool_name())
        self.assertFalse(path_network.is_mcp_tool())
        self.assertEqual(1, len(captured.output))
        self.assertIn("'a__b'", captured.output[0])

    def test_resolve_collisions_reserved_name_wins_when_seen_first(self) -> None:
        """
        Same rule with the reserved name seen first: "alpha" (alias "zzz") sorts before
        "beta", whose alias "alpha" is the other network's own name. "beta" loses.
        """
        alpha: AgentNetwork = self.make_agent_network("alpha")
        alpha.set_as_mcp_tool("zzz")
        beta: AgentNetwork = self.make_agent_network("beta")
        beta.set_as_mcp_tool("alpha")
        all_agent_networks: Dict[str, Dict[str, AgentNetwork]] = {
            StorageClass.PUBLIC: {"alpha": alpha, "beta": beta}
        }

        with self.assertLogs(self.INSTANCE_LOGGER, level=ERROR):
            self.make_restorer().resolve_mcp_tool_name_collisions(all_agent_networks)

        self.assertTrue(alpha.is_mcp_tool())
        self.assertEqual("zzz", alpha.get_mcp_tool_name())
        self.assertFalse(beta.is_mcp_tool())

    def test_resolve_collisions_reserves_name_of_non_mcp_network(self) -> None:
        """
        A public network that is not an MCP tool still reserves its own name: "a/b" may not be
        advertised as "a__b" while a network named "a__b" exists, or a tools/call for "a__b"
        would be answered by "a/b" instead of being refused as not available over MCP.
        """
        path_network: AgentNetwork = self.make_agent_network("a/b")
        path_network.set_as_mcp_tool("a__b")
        plain_network: AgentNetwork = self.make_agent_network("a__b")
        all_agent_networks: Dict[str, Dict[str, AgentNetwork]] = {
            StorageClass.PUBLIC: {"a/b": path_network, "a__b": plain_network}
        }

        with self.assertLogs(self.INSTANCE_LOGGER, level=ERROR):
            self.make_restorer().resolve_mcp_tool_name_collisions(all_agent_networks)

        self.assertFalse(path_network.is_mcp_tool())
        self.assertFalse(plain_network.is_mcp_tool())
        self.assertIs(plain_network, all_agent_networks[StorageClass.PUBLIC]["a__b"])

    NETWORK_HOCON: str = '{ "tools": [ { "name": "front", "function": { "description": "x" } } ] }\n'

    def write_registry(self, registry_dir: str) -> List[str]:
        """
        Writes a small registry to disk: four networks, each listed by its own manifest file.

        One entry per manifest keeps the restorer single-threaded per file, which
        sidesteps the known thread-safety problem in pyhocon parsing and makes the
        test deterministic. Collisions are still resolved across all manifests.

        :param registry_dir: The directory to write into
        :return: The manifest file paths, in the order to restore them
        """
        entries: Dict[str, str] = {
            "a/b": '{ "a/b.hocon": { "serve": true, "mcp": true } }',
            "a__b": '{ "a__b.hocon": { "serve": true, "mcp": true } }',
            "c": '{ "c.hocon": { "serve": true, "mcp_name": "calc" } }',
            "d": '{ "d.hocon": { "serve": true, "mcp": false, "mcp_name": "solo" } }',
        }
        manifest_files: List[str] = []
        for network_name, manifest_text in entries.items():
            network_file: str = join(registry_dir, f"{network_name}.hocon")
            makedirs(dirname(network_file), exist_ok=True)
            with open(network_file, "w", encoding="utf-8") as hocon:
                hocon.write(self.NETWORK_HOCON)
            manifest_file: str = join(registry_dir, f"manifest_{network_name.replace('/', '_')}.hocon")
            with open(manifest_file, "w", encoding="utf-8") as manifest:
                manifest.write(manifest_text + "\n")
            manifest_files.append(manifest_file)
        return manifest_files

    def test_restore_wires_mcp_name_and_collision_resolution_end_to_end(self) -> None:
        """
        Restoring real manifest and network files runs the whole chain: the "mcp_name"
        manifest key is honoured, an explicit "mcp": false is not undone by it, and the
        "a/b" vs "a__b" collision is resolved after all manifests are loaded.
        """
        with TemporaryDirectory() as registry_dir:
            manifest_files: List[str] = self.write_registry(registry_dir)
            restorer = RegistryManifestRestorer(manifest_files=manifest_files)
            with self.assertLogs(self.INSTANCE_LOGGER, level=ERROR) as captured:
                networks: Dict[str, Dict[str, AgentNetwork]] = restorer.restore()

        public: Dict[str, AgentNetwork] = networks[StorageClass.PUBLIC]
        self.assertTrue(public["a__b"].is_mcp_tool())
        self.assertEqual("a__b", public["a__b"].get_mcp_tool_name())
        # The nested network lost the collision but is still served.
        self.assertFalse(public["a/b"].is_mcp_tool())
        self.assertTrue(public["c"].is_mcp_tool())
        self.assertEqual("calc", public["c"].get_mcp_tool_name())
        # "mcp": false kept "d" out of MCP and therefore out of the public storage.
        self.assertNotIn("d", public)
        self.assertFalse(networks[StorageClass.PROTECTED]["d"].is_mcp_tool())
        self.assertEqual(1, len(captured.output))
        self.assertIn("'a__b'", captured.output[0])

    def test_resolve_collisions_without_collision_is_silent(self) -> None:
        """
        Distinct tool names leave everything as it was and log nothing.
        """
        top: AgentNetwork = self.make_agent_network(self.TOP_NAME)
        top.set_as_mcp_tool(self.TOP_NAME)
        nested: AgentNetwork = self.make_agent_network(self.NESTED_NAME)
        nested.set_as_mcp_tool(self.NESTED_TOOL_NAME)
        not_mcp: AgentNetwork = self.make_agent_network("plain")
        all_agent_networks: Dict[str, Dict[str, AgentNetwork]] = {
            StorageClass.PUBLIC: {self.TOP_NAME: top, self.NESTED_NAME: nested, "plain": not_mcp}
        }

        with self.assertNoLogs(self.INSTANCE_LOGGER, level=ERROR):
            self.make_restorer().resolve_mcp_tool_name_collisions(all_agent_networks)

        self.assertTrue(top.is_mcp_tool())
        self.assertTrue(nested.is_mcp_tool())
        self.assertFalse(not_mcp.is_mcp_tool())

    def test_resolve_collisions_tolerates_none_entries_and_missing_storage(self) -> None:
        """
        A None entry (unserved network) is skipped, and a map with no public storage is a no-op.
        """
        top: AgentNetwork = self.make_agent_network(self.TOP_NAME)
        top.set_as_mcp_tool(self.TOP_NAME)
        all_agent_networks: Dict[str, Dict[str, AgentNetwork]] = {
            StorageClass.PUBLIC: {"gone": None, self.TOP_NAME: top}
        }
        restorer: RegistryManifestRestorer = self.make_restorer()
        restorer.resolve_mcp_tool_name_collisions(all_agent_networks)
        self.assertTrue(top.is_mcp_tool())

        restorer.resolve_mcp_tool_name_collisions({})
        restorer.resolve_mcp_tool_name_collisions({StorageClass.PROTECTED: {}})
