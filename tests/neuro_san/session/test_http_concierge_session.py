
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

from functools import partial
import json
import os

from unittest import TestCase
from unittest.mock import MagicMock
from unittest.mock import patch

from requests import ConnectionError as RequestsConnectionError
from typing_extensions import override

from neuro_san.session.http_concierge_session import HttpConciergeSession
from neuro_san.session.session_util import SessionUtil


class TestHttpConciergeSession(TestCase):
    """
    Unit tests for HttpConciergeSession.list(): the "agents" listing a server returns is bounded
    by MAX_AGENTS_FROM_EXTERNAL_SERVER on its way back to the caller, the returned dictionary
    always carries the "agents" key the ConciergeSession contract promises, and transport or
    payload failures surface as the ValueError carrying help_message() that the other HTTP
    sessions raise.
    """

    GET_TARGET: str = "neuro_san.session.http_concierge_session.http_get"
    AGENTS: List[Dict[str, Any]] = [
        {"agent_name": "one", "tags": ["a"]},
        {"agent_name": "two", "tags": ["b"]},
        {"agent_name": "three", "tags": ["a", "b"]},
    ]

    @override
    def setUp(self) -> None:
        """
        Pins the environment: MAX_AGENTS_FROM_EXTERNAL_SERVER is removed so a value exported in
        the developer's shell cannot change the listing, and AGENT_SESSION_REQUIRE_HTTPS is set
        to "false" so the plain-http URL these tests build is not rejected before any request.
        """
        # patch.dict snapshots os.environ on start() and restores the whole mapping on stop(),
        # so variables can simply be removed or set here and per test; all of it is undone by
        # the cleanup, which runs even if the test raises.
        env_patcher: Any = patch.dict(os.environ)
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        os.environ.pop(SessionUtil.MAX_AGENTS_ENV_VAR, None)
        os.environ["AGENT_SESSION_REQUIRE_HTTPS"] = "false"

    @staticmethod
    def fake_get(body_text: str, path: str, **kwargs: Any) -> MagicMock:
        """
        Stands in for requests.get(), answering any request with the given body.

        :param body_text: The text of the HTTP response body
        :param path: The URL requested; unused
        :param kwargs: The keyword arguments requests.get() was given; unused
        :return: A MagicMock response with .text set to body_text
        """
        _ = path, kwargs
        response: MagicMock = MagicMock()
        response.text = body_text
        return response

    def patch_get(self, body: Any) -> Any:
        """
        Patches requests.get() in the session module with a fake server returning the given body.

        :param body: The JSON-serialisable body the fake server returns
        :return: The patch context manager; entering it yields the mock get
        """
        return patch(self.GET_TARGET, side_effect=partial(self.fake_get, json.dumps(body)))

    @staticmethod
    def make_session() -> HttpConciergeSession:
        """
        Builds a session against a fixed host and port; nothing is ever actually connected to.

        :return: A new HttpConciergeSession
        """
        return HttpConciergeSession(host="localhost", port="8080")

    def test_list_returns_full_listing_by_default(self) -> None:
        """
        With no limit set, every agent the server lists comes back, from one GET to /list.
        """
        session: HttpConciergeSession = self.make_session()
        with self.patch_get({"agents": self.AGENTS}) as mock_get:
            result: Dict[str, Any] = session.list({})
        self.assertEqual(self.AGENTS, result["agents"])
        self.assertEqual(1, mock_get.call_count)
        self.assertTrue(mock_get.call_args.args[0].endswith("/list"))

    def test_list_applies_max_agents_limit(self) -> None:
        """
        With MAX_AGENTS_FROM_EXTERNAL_SERVER set, only the first N agents the server listed come back.
        """
        os.environ[SessionUtil.MAX_AGENTS_ENV_VAR] = "2"
        session: HttpConciergeSession = self.make_session()
        with self.patch_get({"agents": self.AGENTS}):
            result: Dict[str, Any] = session.list({})
        self.assertEqual(self.AGENTS[:2], result["agents"])

    def test_list_keeps_other_keys_from_server(self) -> None:
        """
        Bounding the listing does not drop anything else the server put in its response.
        """
        os.environ[SessionUtil.MAX_AGENTS_ENV_VAR] = "1"
        session: HttpConciergeSession = self.make_session()
        with self.patch_get({"agents": self.AGENTS, "extra": "kept"}):
            result: Dict[str, Any] = session.list({})
        self.assertEqual("kept", result["extra"])
        self.assertEqual(self.AGENTS[:1], result["agents"])

    def test_list_supplies_agents_key_when_server_omits_it(self) -> None:
        """
        The ConciergeSession contract says the result always has an "agents" key, so a server
        response without one comes back as an empty listing rather than a KeyError for the caller.
        """
        session: HttpConciergeSession = self.make_session()
        with self.patch_get({}):
            result: Dict[str, Any] = session.list({})
        self.assertEqual([], result["agents"])

    def test_list_passes_non_list_agents_through_even_with_limit(self) -> None:
        """
        A server that sends "agents": null gets that handed back unchanged even when a limit is
        set, rather than list() raising from a slice of None: the malformed shape is left for
        the caller to notice, the same as it is without a limit.
        """
        os.environ[SessionUtil.MAX_AGENTS_ENV_VAR] = "1"
        session: HttpConciergeSession = self.make_session()
        with self.patch_get({"agents": None}):
            result: Dict[str, Any] = session.list({})
        self.assertIsNone(result["agents"])

    def test_list_wraps_transport_failure_in_value_error(self) -> None:
        """
        Failing to reach the server surfaces as a ValueError carrying help_message() for the
        /list request path, with the original exception chained as its cause so the real
        reason is still in the traceback.
        """
        session: HttpConciergeSession = self.make_session()
        with patch(self.GET_TARGET, side_effect=RequestsConnectionError("refused")):
            with self.assertRaises(ValueError) as context:
                session.list({})
        self.assertIsInstance(context.exception.__cause__, RequestsConnectionError)
        self.assertIn(session.get_request_path("list"), str(context.exception))

    def test_list_wraps_non_dict_body_in_value_error(self) -> None:
        """
        A body that parses but is not a dictionary (here JSON null) is reported the same way as
        a transport failure, since the caller cannot do anything useful with it either; the
        chained cause is the AttributeError from treating None as a dictionary.
        """
        session: HttpConciergeSession = self.make_session()
        with self.patch_get(None):
            with self.assertRaises(ValueError) as context:
                session.list({})
        self.assertIsInstance(context.exception.__cause__, AttributeError)
        self.assertIn(session.get_request_path("list"), str(context.exception))
