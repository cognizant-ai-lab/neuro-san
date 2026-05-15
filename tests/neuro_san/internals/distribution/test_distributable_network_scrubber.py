
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
"""
Unit tests for DistributableNetworkScrubber.

Pure-function tests; do not require any servers running.  The scrubber is
security-critical, so the assertions here are the closest thing the MVP has
to a "do not regress this" gate.
"""
import base64
import unittest

from neuro_san.internals.distribution.distributable_network_scrubber import (
    AGENT_WEB_PROTOCOL_VERSION,
    DistributableNetworkScrubber,
    DistributableScrubberError,
)
from neuro_san.internals.graph.registry.agent_network import AgentNetwork


class TestDistributableNetworkScrubber(unittest.TestCase):
    """Pure scrubber tests using a coded tool that already exists in-tree."""

    # We use the existing math_guy.calculator.Calculator so the scrubber can
    # actually resolve a real source file for the client_side branch.
    REAL_CLASS_REF = "neuro_san.coded_tools.math_guy.calculator.Calculator"

    def _build_network(self, tools):
        cfg = {
            "llm_config": {
                "model_name": "gpt-4o-mini",
                "api_key": "sk-very-secret",
                "temperature": 0.2,
            },
            "tools": tools,
        }
        return AgentNetwork(cfg, "test_net")

    def _scrub(self, network):
        scrubber = DistributableNetworkScrubber(
            agent_tool_path="neuro_san.coded_tools.test_net"
        )
        return scrubber.scrub(network, "http://origin.example:9000")

    def test_strips_top_level_api_key(self):
        net = self._build_network([
            {"name": "front", "function": {"description": "hi"},
             "instructions": "ok", "tools": []},
        ])
        wire = self._scrub(net)
        self.assertNotIn("api_key", wire["llm_config"])
        self.assertEqual(wire["llm_config"]["model_name"], "gpt-4o-mini")

    def test_strips_per_agent_api_key(self):
        net = self._build_network([
            {"name": "front", "function": {"description": "hi"},
             "instructions": "ok", "tools": [],
             "llm_config": {"model_name": "x", "azure_api_key": "leak-me-not"}},
        ])
        wire = self._scrub(net)
        agent_llm = wire["tools"][0].get("llm_config", {})
        self.assertNotIn("azure_api_key", agent_llm)

    def test_server_class_rewritten_to_coded_tool_url(self):
        net = self._build_network([
            {"name": "front", "function": {"description": "hi"},
             "instructions": "ok", "tools": ["srv"]},
            {"name": "srv", "function": {"description": "x",
                                          "parameters": {"type": "object", "properties": {}}},
             "class": self.REAL_CLASS_REF},
        ])
        wire = self._scrub(net)
        srv_spec = next(t for t in wire["tools"] if t["name"] == "srv")
        self.assertNotIn("class", srv_spec)
        self.assertNotIn("toolbox", srv_spec)
        self.assertEqual(
            srv_spec["coded_tool_url"],
            "http://origin.example:9000/api/v1/test_net/tool/srv",
        )

    def test_client_side_class_ships_source_with_integrity(self):
        net = self._build_network([
            {"name": "front", "function": {"description": "hi"},
             "instructions": "ok", "tools": ["cli"]},
            {"name": "cli", "function": {"description": "x",
                                          "parameters": {"type": "object", "properties": {}}},
             "client_side": True,
             "class": self.REAL_CLASS_REF},
        ])
        wire = self._scrub(net)
        cli_spec = next(t for t in wire["tools"] if t["name"] == "cli")
        self.assertNotIn("class", cli_spec)
        self.assertNotIn("coded_tool_url", cli_spec)
        self.assertTrue(cli_spec.get("client_side"))
        self.assertEqual(cli_spec["client_side_class"], "Calculator")
        # Source decodes and starts with the license header used everywhere.
        decoded = base64.b64decode(cli_spec["client_side_source"]).decode("utf-8")
        self.assertIn("Cognizant", decoded)
        self.assertTrue(cli_spec["integrity"].startswith("sha256-"))

    def test_protocol_metadata_is_stamped(self):
        net = self._build_network([
            {"name": "front", "function": {"description": "hi"},
             "instructions": "ok", "tools": []},
        ])
        wire = self._scrub(net)
        meta = wire["agent_web"]
        self.assertEqual(meta["protocol_version"], AGENT_WEB_PROTOCOL_VERSION)
        self.assertEqual(meta["origin"], "http://origin.example:9000")
        self.assertEqual(meta["network_name"], "test_net")
        self.assertIn("published_at", meta)

    def test_commondefs_block_is_dropped(self):
        # The AgentNetworkRestorer.filter_config resolves commondefs before
        # the AgentNetwork is built; the scrubber separately drops any leftover.
        net = self._build_network([
            {"name": "front", "function": {"description": "hi"},
             "instructions": "ok", "tools": []},
        ])
        # Inject a leftover commondefs block to verify the scrubber strips it.
        net.config["commondefs"] = {"replacement_strings": {"k": "v"}}
        wire = self._scrub(net)
        self.assertNotIn("commondefs", wire)

    def test_does_not_mutate_input(self):
        agents = [
            {"name": "srv", "function": {"description": "x",
                                          "parameters": {"type": "object", "properties": {}}},
             "class": self.REAL_CLASS_REF},
        ]
        net = self._build_network(agents)
        original_class = agents[0]["class"]
        original_api_key = net.get_config()["llm_config"]["api_key"]
        self._scrub(net)
        self.assertEqual(agents[0]["class"], original_class,
                         "scrubber must not mutate the input agent spec")
        self.assertEqual(net.get_config()["llm_config"]["api_key"], original_api_key,
                         "scrubber must not mutate the input llm_config")

    def test_refuses_when_class_cant_be_resolved_for_client_side(self):
        net = self._build_network([
            {"name": "cli", "function": {"description": "x",
                                          "parameters": {"type": "object", "properties": {}}},
             "client_side": True,
             "class": "nonexistent.module.GhostTool"},
        ])
        with self.assertRaises(DistributableScrubberError):
            self._scrub(net)

    def test_value_that_looks_like_credential_is_refused(self):
        # A user might put a literal sk-... value in a non-secret-named key by mistake.
        # The scrubber's post-condition heuristic should refuse to publish.
        net = self._build_network([
            {"name": "front", "function": {"description": "hi"},
             "instructions": "ok", "tools": [],
             "llm_config": {"model_name": "x",
                             "endpoint": "sk-ABCDEFGHIJKLMNOPQRSTUVWX1234567890"}},
        ])
        with self.assertRaises(DistributableScrubberError):
            self._scrub(net)


if __name__ == "__main__":
    unittest.main()
