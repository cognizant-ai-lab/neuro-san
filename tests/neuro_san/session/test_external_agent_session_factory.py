
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
from asyncio import run_coroutine_threadsafe
from concurrent.futures import Future
from typing import Any
from typing import Coroutine
from typing import Dict

import os

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from typing_extensions import override

from leaf_common.asyncio.asyncio_executor import AsyncioExecutor

from neuro_san.interfaces.async_agent_session import AsyncAgentSession
from neuro_san.internals.interfaces.storage_class import StorageClass
from neuro_san.session.async_direct_agent_session import AsyncDirectAgentSession
from neuro_san.session.async_http_service_agent_session import AsyncHttpServiceAgentSession
from neuro_san.session.external_agent_session_factory import ExternalAgentSessionFactory


class TestExternalAgentSessionFactory(IsolatedAsyncioTestCase):
    """
    Unit tests for ExternalAgentSessionFactory class.

    Most of these exercise the http-session path (use_direct=False), checking
    that the scheme parsed out of an external agent reference is honored
    when the factory builds the url the session will call. The direct_* tests
    check the order in which a direct factory consults its storages.
    """

    # Seconds to wait for a coroutine scheduled on the executor's event loop
    TIMEOUT_SECONDS: float = 10.0

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

        # Mock storages of a direct factory, set by create_direct_factory()
        self.public_storage: MagicMock = None
        self.fetched_storage: MagicMock = None

    async def test_https_location_builds_https_url(self) -> None:
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
            await self.factory.create_session_from_location_dict(agent_location, self.invocation_context)
        self.assertIsInstance(session, AsyncHttpServiceAgentSession)
        self.assertEqual(session.get_request_path("function"), "https://h:443/api/v1/deep/math_guy/function")

    async def test_http_location_without_port_uses_default_http_port(self) -> None:
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
            await self.factory.create_session_from_location_dict(agent_location, self.invocation_context)
        self.assertIsInstance(session, AsyncHttpServiceAgentSession)
        self.assertEqual(session.get_request_path("function"), "http://h:8080/api/v1/deep/math_guy/function")

    async def test_legacy_location_without_scheme_is_http(self) -> None:
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
            await self.factory.create_session_from_location_dict(agent_location, self.invocation_context)
        self.assertIsInstance(session, AsyncHttpServiceAgentSession)
        self.assertIsNone(session.security_cfg)
        self.assertEqual(session.get_request_path("function"), "http://h:8080/api/v1/math_guy/function")

    async def test_none_location_returns_none(self) -> None:
        """
        Tests that an unparseable reference (None location) yields no session
        rather than an http session pointed at nothing.
        """
        session: AsyncAgentSession = \
            await self.factory.create_session_from_location_dict(None, self.invocation_context)
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

    async def test_async_create_session_https_reference_end_to_end(self) -> None:
        """
        Tests the parse-then-build path for the reference shape that used to
        come out as http://host:8080: an https url with no port and a nested
        registry path now yields an https url on port 443.
        """
        session: AsyncAgentSession = \
            await self.factory.async_create_session("https://neuro-san.decisionai.ml/deep/math_guy",
                                                    self.invocation_context)
        self.assertIsInstance(session, AsyncHttpServiceAgentSession)
        self.assertEqual(session.get_request_path("function"),
                         "https://neuro-san.decisionai.ml:443/api/v1/deep/math_guy/function")

    async def test_require_https_allows_https_reference(self) -> None:
        """
        Tests that with AGENT_SESSION_REQUIRE_HTTPS=true an https reference
        still builds its url, since the session now really is https.
        """
        session: AsyncAgentSession = \
            await self.factory.async_create_session("https://neuro-san.decisionai.ml/deep/math_guy",
                                                    self.invocation_context)
        with patch.dict(os.environ, {"AGENT_SESSION_REQUIRE_HTTPS": "true"}):
            path: str = session.get_request_path("function")
        self.assertEqual(path, "https://neuro-san.decisionai.ml:443/api/v1/deep/math_guy/function")

    async def test_require_https_rejects_http_reference(self) -> None:
        """
        Tests that with AGENT_SESSION_REQUIRE_HTTPS=true an http reference is
        rejected when its url is built, matching the hardening contract.
        """
        session: AsyncAgentSession = \
            await self.factory.async_create_session("http://neuro-san.decisionai.ml/deep/math_guy",
                                                    self.invocation_context)
        with patch.dict(os.environ, {"AGENT_SESSION_REQUIRE_HTTPS": "true"}):
            with self.assertRaises(ValueError):
                session.get_request_path("function")

    async def test_async_create_session_ipv6_https_reference_builds_bracketed_url(self) -> None:
        """
        Tests that a bracketed IPv6 https reference ends up as a well-formed
        https url with the brackets kept around the address and the 443
        default port after them.
        """
        session: AsyncAgentSession = \
            await self.factory.async_create_session("https://[2001:db8::1]/deep/math_guy", self.invocation_context)
        self.assertIsInstance(session, AsyncHttpServiceAgentSession)
        self.assertEqual(session.get_request_path("function"),
                         "https://[2001:db8::1]:443/api/v1/deep/math_guy/function")

    def start_executor(self) -> AsyncioExecutor:
        """
        Starts an AsyncioExecutor and makes the invocation context return it.

        :return: The started AsyncioExecutor
        """
        executor: AsyncioExecutor = AsyncioExecutor()
        executor.start()
        # Do not join the loop thread: if create_session() regresses and blocks the
        # executor's loop, a join would hang the test run instead of failing the test.
        self.addCleanup(executor.shutdown, False)
        self.invocation_context.get_asyncio_executor.return_value = executor
        return executor

    async def create_session_from_coroutine(self, agent_url: str) -> AsyncAgentSession:
        """
        Calls the synchronous create_session() from within a coroutine.

        :param agent_url: The external agent reference passed to create_session()
        :return: The session returned by create_session()
        """
        return self.factory.create_session(agent_url, self.invocation_context)

    def test_create_session_on_executor_loop_raises(self) -> None:
        """
        Tests that create_session() called from a coroutine on the event loop of the
        invocation's AsyncioExecutor raises RuntimeError instead of blocking that loop
        on a coroutine scheduled onto itself.
        """
        executor: AsyncioExecutor = self.start_executor()
        coroutine: Coroutine[Any, Any, AsyncAgentSession] = \
            self.create_session_from_coroutine("https://neuro-san.decisionai.ml/deep/math_guy")
        future: Future = run_coroutine_threadsafe(coroutine, executor.get_event_loop())
        with self.assertRaises(RuntimeError):
            future.result(timeout=self.TIMEOUT_SECONDS)

    def test_create_session_off_executor_loop_returns_session(self) -> None:
        """
        Tests that create_session() called from a thread with no running event loop
        runs async_create_session() on the executor's loop and returns its session.
        """
        self.start_executor()
        session: AsyncAgentSession = \
            self.factory.create_session("https://neuro-san.decisionai.ml/deep/math_guy", self.invocation_context)
        self.assertIsInstance(session, AsyncHttpServiceAgentSession)
        self.assertEqual(session.get_request_path("function"),
                         "https://neuro-san.decisionai.ml:443/api/v1/deep/math_guy/function")

    @staticmethod
    def create_storage(agent_network: Any) -> MagicMock:
        """
        Creates a mock AgentStorageSource whose provider yields the given agent network.

        :param agent_network: The agent network the provider returns, or None for a miss
        :return: The mock storage source
        """
        provider: MagicMock = MagicMock()
        provider.get_agent_network.return_value = agent_network
        storage: MagicMock = MagicMock()
        storage.async_get_agent_network_provider = AsyncMock(return_value=provider)
        return storage

    def create_direct_factory(self, public_network: Any, fetched_network: Any) -> ExternalAgentSessionFactory:
        """
        Creates a direct factory with one public and one fetched mock storage.

        :param public_network: The agent network the public storage yields, or None for a miss
        :param fetched_network: The agent network the fetched storage yields, or None for a miss
        :return: The direct factory
        """
        self.public_storage = self.create_storage(public_network)
        self.fetched_storage = self.create_storage(fetched_network)
        storage_dict: Dict[str, Any] = {
            StorageClass.PUBLIC: self.public_storage,
            StorageClass.FETCHED: self.fetched_storage,
        }
        return ExternalAgentSessionFactory(use_direct=True, network_storage_dict=storage_dict)

    async def test_direct_fetched_is_last_resort_before_http(self) -> None:
        """
        Tests that a direct factory fetches by the full URL when no local storage has the agent
        """
        agent_url: str = "https://example.com/nets/math_guy.hocon"
        factory: ExternalAgentSessionFactory = self.create_direct_factory(None, MagicMock())

        session: AsyncAgentSession = await factory.async_create_session(agent_url, self.invocation_context)
        self.assertIsInstance(session, AsyncDirectAgentSession)
        self.fetched_storage.async_get_agent_network_provider.assert_awaited_once_with(agent_url)

    async def test_direct_local_storage_wins_over_fetched(self) -> None:
        """
        Tests that a direct factory uses a local agent network without fetching anything
        """
        factory: ExternalAgentSessionFactory = self.create_direct_factory(MagicMock(), MagicMock())

        session: AsyncAgentSession = await factory.async_create_session("/math_guy", self.invocation_context)
        self.assertIsInstance(session, AsyncDirectAgentSession)
        self.public_storage.async_get_agent_network_provider.assert_awaited_once_with("math_guy")
        self.fetched_storage.async_get_agent_network_provider.assert_not_awaited()

    async def test_direct_fetch_miss_falls_back_to_http(self) -> None:
        """
        Tests that a direct factory makes an http session when the fetched storage has no agent network
        """
        agent_url: str = "https://example.com/math_guy"
        factory: ExternalAgentSessionFactory = self.create_direct_factory(None, None)

        session: AsyncAgentSession = await factory.async_create_session(agent_url, self.invocation_context)
        self.assertIsInstance(session, AsyncHttpServiceAgentSession)
        self.fetched_storage.async_get_agent_network_provider.assert_awaited_once_with(agent_url)

    async def test_direct_location_without_agent_url_does_not_fetch(self) -> None:
        """
        Tests that a location dict without an "agent_url" key, as built by older callers, never fetches
        """
        agent_location: Dict[str, str] = {
            "host": "example.com",
            "port": "443",
            "agent_name": "nets/math_guy.hocon",
            "scheme": "https",
        }
        factory: ExternalAgentSessionFactory = self.create_direct_factory(None, MagicMock())

        session: AsyncAgentSession = \
            await factory.create_session_from_location_dict(agent_location, self.invocation_context)
        self.assertIsInstance(session, AsyncHttpServiceAgentSession)
        self.fetched_storage.async_get_agent_network_provider.assert_not_awaited()
