
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

import os

from unittest import TestCase
from unittest.mock import MagicMock
from unittest.mock import patch

from typing_extensions import override

from neuro_san.interfaces.async_agent_session import AsyncAgentSession
from neuro_san.session.async_http_service_agent_session import AsyncHttpServiceAgentSession
from neuro_san.session.external_agent_session_factory import ExternalAgentSessionFactory


class TestExternalAgentSessionFactory(TestCase):
    """
    Unit tests for ExternalAgentSessionFactory class.

    These exercise the http-session path only (use_direct=False), checking
    that the scheme parsed out of an external agent reference is honored
    when the factory builds the url the session will call.
    """

    @override
    def setUp(self) -> None:
        """
        Builds a non-direct factory and a minimal invocation context whose
        metadata is empty, so every session gets a real (if empty) header dict.

        Also isolates the process environment so AGENT_SESSION_REQUIRE_HTTPS
        starts out unset for every test, regardless of the developer's shell.
        """
        # The shipped Dockerfile defaults AGENT_SESSION_REQUIRE_HTTPS to "true", so a developer
        # who mirrors that in their shell would otherwise see the plain-http tests below raise
        # from get_request_path(). Snapshot the environment, drop the variable, and restore the
        # snapshot on cleanup so the two test_require_https_* cases can still opt in per-test.
        env_patcher: Any = patch.dict(os.environ)
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        os.environ.pop("AGENT_SESSION_REQUIRE_HTTPS", None)

        self.factory: ExternalAgentSessionFactory = ExternalAgentSessionFactory(use_direct=False)
        self.invocation_context: MagicMock = MagicMock()
        self.invocation_context.get_metadata.return_value = {}
        # No server port configured; only the localhost rule would consume it anyway.
        self.invocation_context.get_port.return_value = None

    def test_https_location_builds_https_url(self) -> None:
        """
        Tests that a location dict whose scheme is https yields a session that
        talks https on the parsed port and keeps the nested agent name in the path.
        """
        agent_location: Dict[str, str] = {
            "host": "h",
            "port": "443",
            "agent_name": "deep/math_guy",
            "scheme": "https",
        }
        session: AsyncAgentSession = \
            self.factory.create_session_from_location_dict(agent_location, self.invocation_context)
        self.assertIsInstance(session, AsyncHttpServiceAgentSession)
        self.assertEqual(session.get_request_path("function"), "https://h:443/api/v1/deep/math_guy/function")

    def test_http_location_without_port_uses_default_http_port(self) -> None:
        """
        Tests that an http location with no port falls through to the session
        layer's default http port and stays on plain http.
        """
        agent_location: Dict[str, str] = {
            "host": "h",
            "port": None,
            "agent_name": "deep/math_guy",
            "scheme": "http",
        }
        session: AsyncAgentSession = \
            self.factory.create_session_from_location_dict(agent_location, self.invocation_context)
        self.assertIsInstance(session, AsyncHttpServiceAgentSession)
        self.assertEqual(session.get_request_path("function"), "http://h:8080/api/v1/deep/math_guy/function")

    def test_legacy_location_without_scheme_is_http(self) -> None:
        """
        Tests that a location dict built by an older caller, with no "scheme"
        key at all, keeps the plain http behavior it always had.
        """
        agent_location: Dict[str, str] = {
            "host": "h",
            "port": "8080",
            "agent_name": "math_guy",
        }
        session: AsyncAgentSession = \
            self.factory.create_session_from_location_dict(agent_location, self.invocation_context)
        self.assertIsInstance(session, AsyncHttpServiceAgentSession)
        self.assertIsNone(session.security_cfg)
        self.assertEqual(session.get_request_path("function"), "http://h:8080/api/v1/math_guy/function")

    def test_none_location_returns_none(self) -> None:
        """
        Tests that an unparseable reference (None location) yields no session
        rather than an http session pointed at nothing.
        """
        session: AsyncAgentSession = \
            self.factory.create_session_from_location_dict(None, self.invocation_context)
        self.assertIsNone(session)

    def test_get_security_cfg_only_set_for_https(self) -> None:
        """
        Tests the scheme-to-security_cfg mapping directly: https gets an empty
        (non-None) dict, http and a missing scheme get None.
        """
        https_cfg: Dict[str, Any] = ExternalAgentSessionFactory.get_security_cfg({"scheme": "https"})
        http_cfg: Dict[str, Any] = ExternalAgentSessionFactory.get_security_cfg({"scheme": "http"})
        legacy_cfg: Dict[str, Any] = ExternalAgentSessionFactory.get_security_cfg({})
        self.assertEqual(https_cfg, {})
        self.assertIsNone(http_cfg)
        self.assertIsNone(legacy_cfg)

    def test_create_session_https_reference_end_to_end(self) -> None:
        """
        Tests the parse-then-build path for the reference shape that used to
        come out as http://host:8080: an https url with no port and a nested
        registry path now yields an https url on port 443.
        """
        session: AsyncAgentSession = \
            self.factory.create_session("https://neuro-san.decisionai.ml/deep/math_guy", self.invocation_context)
        self.assertIsInstance(session, AsyncHttpServiceAgentSession)
        self.assertEqual(session.get_request_path("function"),
                         "https://neuro-san.decisionai.ml:443/api/v1/deep/math_guy/function")

    def test_require_https_allows_https_reference(self) -> None:
        """
        Tests that with AGENT_SESSION_REQUIRE_HTTPS=true an https reference
        still builds its url, since the session now really is https.
        """
        session: AsyncAgentSession = \
            self.factory.create_session("https://neuro-san.decisionai.ml/deep/math_guy", self.invocation_context)
        with patch.dict(os.environ, {"AGENT_SESSION_REQUIRE_HTTPS": "true"}):
            path: str = session.get_request_path("function")
        self.assertEqual(path, "https://neuro-san.decisionai.ml:443/api/v1/deep/math_guy/function")

    def test_require_https_rejects_http_reference(self) -> None:
        """
        Tests that with AGENT_SESSION_REQUIRE_HTTPS=true an http reference is
        rejected when its url is built, matching the hardening contract.
        """
        session: AsyncAgentSession = \
            self.factory.create_session("http://neuro-san.decisionai.ml/deep/math_guy", self.invocation_context)
        with patch.dict(os.environ, {"AGENT_SESSION_REQUIRE_HTTPS": "true"}):
            with self.assertRaises(ValueError):
                session.get_request_path("function")
