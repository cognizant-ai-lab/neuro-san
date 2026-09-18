
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
from typing import Dict

from unittest import TestCase

from neuro_san.internals.utils.external_agent_parsing import ExternalAgentParsing


class TestExternalAgentParsing(TestCase):
    """
    Unit tests for ExternalAgentParsing class.
    """

    def test_parse_external_agent_valid_url(self) -> None:
        """
        Tests that a well-formed external agent URL parses into its parts.
        """
        agent_location: Dict[str, str] = \
            ExternalAgentParsing.parse_external_agent("http://myhost:8080/my_agent")
        self.assertIsNotNone(agent_location)
        self.assertEqual(agent_location.get("host"), "myhost")
        self.assertEqual(agent_location.get("port"), "8080")
        self.assertEqual(agent_location.get("agent_name"), "my_agent")

    def test_parse_external_agent_unparseable_url_returns_none(self) -> None:
        """
        Tests that a url that urlparse cannot handle (a mismatched bracket,
        read as an invalid IPv6 netloc) returns None per this method's contract
        instead of raising ValueError. Such urls can reach this code from
        agent hocons: ToolsShapeValidator does not inspect MCP dict
        internals and UrlNetworkValidator accepts any http(s)-prefixed
        string.
        """
        agent_location: Dict[str, str] = \
            ExternalAgentParsing.parse_external_agent("http://[oops/mcp")
        self.assertIsNone(agent_location)

    def test_is_external_agent_unparseable_url_returns_false(self) -> None:
        """
        Tests that is_external_agent reports False for an unparseable url
        instead of raising ValueError. Before the fix this crashed both
        connectivity reporting and runtime external-tool resolution.
        """
        self.assertFalse(ExternalAgentParsing.is_external_agent("http://[oops/mcp"))
        self.assertFalse(ExternalAgentParsing.is_external_agent("http://[oops/mcp::t1"))

    def test_parse_external_agent_https_without_port_defaults_to_443(self) -> None:
        """
        Tests that an https reference without an explicit port gets the
        well-known https port rather than being left to the session layer's
        8080 http default, and that a nested-registry path survives as the
        agent name.
        """
        agent_location: Dict[str, str] = \
            ExternalAgentParsing.parse_external_agent("https://neuro-san.decisionai.ml/deep/math_guy")
        self.assertIsNotNone(agent_location)
        self.assertEqual(agent_location.get("host"), "neuro-san.decisionai.ml")
        self.assertEqual(agent_location.get("port"), "443")
        self.assertEqual(agent_location.get("agent_name"), "deep/math_guy")
        self.assertEqual(agent_location.get("scheme"), "https")

    def test_parse_external_agent_https_with_explicit_port_keeps_it(self) -> None:
        """
        Tests that an explicit port in an https reference is kept as-is
        instead of being overridden by the https default.
        """
        agent_location: Dict[str, str] = \
            ExternalAgentParsing.parse_external_agent("https://agents.example.com:8443/deep/math_guy")
        self.assertIsNotNone(agent_location)
        self.assertEqual(agent_location.get("host"), "agents.example.com")
        self.assertEqual(agent_location.get("port"), "8443")
        self.assertEqual(agent_location.get("scheme"), "https")

    def test_parse_external_agent_http_without_port_leaves_port_none(self) -> None:
        """
        Tests that an http reference without an explicit port leaves the port
        as None so the session layer keeps applying its own http default,
        while still reporting the scheme.
        """
        agent_location: Dict[str, str] = \
            ExternalAgentParsing.parse_external_agent("http://agents.example.com/math_guy")
        self.assertIsNotNone(agent_location)
        self.assertEqual(agent_location.get("host"), "agents.example.com")
        self.assertIsNone(agent_location.get("port"))
        self.assertEqual(agent_location.get("agent_name"), "math_guy")
        self.assertEqual(agent_location.get("scheme"), "http")

    def test_parse_external_agent_same_server_uses_server_port(self) -> None:
        """
        Tests that a same-server "/name" reference resolves to localhost on
        the configured server port and reports an empty scheme.
        """
        agent_location: Dict[str, str] = \
            ExternalAgentParsing.parse_external_agent("/deep/math_guy", server_port=9000)
        self.assertIsNotNone(agent_location)
        self.assertEqual(agent_location.get("host"), "localhost")
        self.assertEqual(agent_location.get("port"), 9000)
        self.assertEqual(agent_location.get("agent_name"), "deep/math_guy")
        self.assertEqual(agent_location.get("scheme"), "")

    def test_parse_external_agent_same_server_without_server_port(self) -> None:
        """
        Tests that a same-server "/name" reference with no server port
        configured leaves the port as None rather than inventing one.
        """
        agent_location: Dict[str, str] = \
            ExternalAgentParsing.parse_external_agent("/deep/math_guy")
        self.assertIsNotNone(agent_location)
        self.assertEqual(agent_location.get("host"), "localhost")
        self.assertIsNone(agent_location.get("port"))
        self.assertEqual(agent_location.get("scheme"), "")

    def test_parse_external_agent_https_localhost_prefers_server_port(self) -> None:
        """
        Tests that the localhost rule wins over the https port default: an
        https reference to localhost without a port uses the configured
        server port, while the scheme is still reported as https.
        """
        agent_location: Dict[str, str] = \
            ExternalAgentParsing.parse_external_agent("https://localhost/deep/math_guy", server_port=9000)
        self.assertIsNotNone(agent_location)
        self.assertEqual(agent_location.get("host"), "localhost")
        self.assertEqual(agent_location.get("port"), 9000)
        self.assertEqual(agent_location.get("scheme"), "https")

    def test_parse_external_agent_ipv6_https_without_port_defaults_to_443(self) -> None:
        """
        Tests that a bracketed IPv6 https reference keeps its brackets as the host
        and still receives the https default port, instead of being split on the
        wrong colon into a malformed host and port.
        """
        agent_location: Dict[str, str] = \
            ExternalAgentParsing.parse_external_agent("https://[2001:db8::1]/deep/math_guy")
        self.assertIsNotNone(agent_location)
        self.assertEqual(agent_location.get("host"), "[2001:db8::1]")
        self.assertEqual(agent_location.get("port"), "443")
        self.assertEqual(agent_location.get("scheme"), "https")
        self.assertEqual(agent_location.get("agent_name"), "deep/math_guy")

    def test_parse_external_agent_ipv6_with_explicit_port_keeps_port(self) -> None:
        """
        Tests that an explicit port on a bracketed IPv6 reference is the port
        after the closing bracket, not a piece of the address.
        """
        agent_location: Dict[str, str] = \
            ExternalAgentParsing.parse_external_agent("http://[::1]:8042/math_guy")
        self.assertIsNotNone(agent_location)
        self.assertEqual(agent_location.get("host"), "[::1]")
        self.assertEqual(agent_location.get("port"), "8042")
        self.assertEqual(agent_location.get("scheme"), "http")

    def test_parse_external_agent_non_numeric_port_returns_none(self) -> None:
        """
        Tests that a reference whose port is not a number is treated as
        unparseable and returns None, rather than handing a bogus port to
        the session layer.
        """
        agent_location: Dict[str, str] = \
            ExternalAgentParsing.parse_external_agent("http://agents.example.com:abc/math_guy")
        self.assertIsNone(agent_location)
        self.assertFalse(ExternalAgentParsing.is_external_agent("http://agents.example.com:abc/math_guy"))

    def test_parse_external_agent_explicit_port_text_is_preserved(self) -> None:
        """
        Tests that an explicit port is returned exactly as written in the
        reference, so a leading zero is not normalized away even though the
        port is validated as a number.
        """
        agent_location: Dict[str, str] = \
            ExternalAgentParsing.parse_external_agent("https://agents.example.com:0443/math_guy")
        self.assertIsNotNone(agent_location)
        self.assertEqual(agent_location.get("port"), "0443")
        self.assertEqual(agent_location.get("scheme"), "https")

    def test_parse_external_agent_authority_without_host_returns_none(self) -> None:
        """
        Tests that an authority with userinfo but no host is treated as
        unparseable instead of falling back to localhost, which would turn a
        broken remote reference into a call to a local agent of the same name.
        """
        self.assertIsNone(ExternalAgentParsing.parse_external_agent("http://user@/math_guy"))
        self.assertFalse(ExternalAgentParsing.is_external_agent("http://user@/math_guy"))

    def test_parse_external_agent_port_only_authority_returns_none(self) -> None:
        """
        Tests that an authority consisting of a port alone, with no host, is
        also treated as unparseable rather than defaulting to localhost.
        """
        self.assertIsNone(ExternalAgentParsing.parse_external_agent("http://:8080/math_guy"))

    def test_parse_external_agent_empty_authority_still_means_same_server(self) -> None:
        """
        Tests that a reference with an empty authority keeps resolving to the
        same server, as it always has, so only a present-but-hostless authority
        is rejected.
        """
        agent_location: Dict[str, str] = \
            ExternalAgentParsing.parse_external_agent("http:///math_guy", server_port=9000)
        self.assertIsNotNone(agent_location)
        self.assertEqual(agent_location.get("host"), "localhost")
        self.assertEqual(agent_location.get("port"), 9000)

    def test_parse_external_agent_empty_explicit_port_returns_none(self) -> None:
        """
        Tests that a trailing colon with no port digits is treated as a
        malformed port and returns None, rather than quietly receiving the
        scheme's default port.
        """
        self.assertIsNone(ExternalAgentParsing.parse_external_agent("https://agents.example.com:/math_guy"))
        self.assertIsNone(ExternalAgentParsing.parse_external_agent("http://[::1]:/math_guy"))
        self.assertIsNone(ExternalAgentParsing.parse_external_agent("http://user@agents.example.com:/math_guy"))
