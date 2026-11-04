
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

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List

import json
import os

from unittest import IsolatedAsyncioTestCase

import tornado.httpserver
import tornado.web

from tornado.testing import bind_unused_port

from record_playback_llm_server.cassette import Cassette
from record_playback_llm_server.proxy_state import ProxyState
from record_playback_llm_server.record_playback_llm_server import RecordPlaybackLlmServer
from tests.record_playback_llm_server.counting_upstream import CountingUpstream
from tests.record_playback_llm_server.proxy_test_client import ProxyTestClient
from tests.record_playback_llm_server.rate_limited_upstream import RateLimitedUpstream
from tests.record_playback_llm_server.stream_upstream import StreamUpstream


class TestProxyIntegration(IsolatedAsyncioTestCase):
    """
    In-process record/playback/hybrid behavior against a fake upstream.

    Each test spins up a fake "upstream" Tornado app plus the real proxy application
    on ephemeral loopback ports (via start_app()), so it needs neither a
    real LLM host nor a running neuro-san server.
    """

    async def asyncSetUp(self):
        """
        Create a temporary directory for cassettes and an empty list of started servers.
        """
        self.servers: List[tornado.httpserver.HTTPServer] = []
        # enterContext() removes the directory during cleanup, after asyncTearDown()
        self.tmp_path: Path = Path(self.enterContext(TemporaryDirectory()))

    async def asyncTearDown(self):
        """
        Stop every server started by start_app().
        """
        server: tornado.httpserver.HTTPServer
        # Stop each server started during the test
        for server in self.servers:
            server.stop()

    def start_app(self, app: tornado.web.Application) -> str:
        """
        Bind a Tornado app to an unused loopback port on the test's event loop.

        :param app: The Tornado application to serve.
        :return: The base URL of the started server.
        """
        sock, port = bind_unused_port()
        server = tornado.httpserver.HTTPServer(app)
        server.add_socket(sock)
        self.servers.append(server)
        return f"http://127.0.0.1:{port}"

    async def test_record_then_playback_json(self):
        """Record a one-shot response, then replay it without hitting upstream."""
        box = {"n": 0}
        upstream = self.start_app(
            tornado.web.Application([(ProxyTestClient.CHAT_PATH, CountingUpstream, {"box": box})]))
        path = str(self.tmp_path / "c.json")

        rec = ProxyState(mode=ProxyState.MODE_RECORD, cassette=Cassette(path, use_multi_mode=False),
                         upstream=ProxyTestClient.upstream_client(upstream))
        rec_url = self.start_app(RecordPlaybackLlmServer.build_app(rec))
        code, body = await ProxyTestClient.post(rec_url + ProxyTestClient.CHAT_PATH, ProxyTestClient.PAYLOAD)
        assert code == 200 and ProxyTestClient.content(body) == "resp-1"
        assert box["n"] == 1

        pb = ProxyState(mode=ProxyState.MODE_PLAYBACK, cassette=Cassette(path, use_multi_mode=False))
        pb_url = self.start_app(RecordPlaybackLlmServer.build_app(pb))
        code2, body2 = await ProxyTestClient.post(pb_url + ProxyTestClient.CHAT_PATH, ProxyTestClient.PAYLOAD)
        assert code2 == 200 and json.loads(body2) == json.loads(body)   # JSON equivalent replay
        assert box["n"] == 1                                            # upstream NOT hit on playback

    async def test_record_then_playback_stream(self):
        """Record a streamed SSE response, then replay it without hitting upstream."""
        box = {"n": 0}
        upstream = self.start_app(tornado.web.Application([(ProxyTestClient.CHAT_PATH, StreamUpstream, {"box": box})]))
        path = str(self.tmp_path / "c.json")

        rec = ProxyState(mode=ProxyState.MODE_RECORD, cassette=Cassette(path, use_multi_mode=False),
                         upstream=ProxyTestClient.upstream_client(upstream))
        rec_url = self.start_app(RecordPlaybackLlmServer.build_app(rec))
        code, body = await ProxyTestClient.post(
            rec_url + ProxyTestClient.CHAT_PATH, ProxyTestClient.PAYLOAD, stream=True)
        assert code == 200 and b"from" in body and b"[DONE]" in body

        pb = ProxyState(mode=ProxyState.MODE_PLAYBACK, cassette=Cassette(path, use_multi_mode=False))
        pb_url = self.start_app(RecordPlaybackLlmServer.build_app(pb))
        code2, body2 = await ProxyTestClient.post(
            pb_url + ProxyTestClient.CHAT_PATH, ProxyTestClient.PAYLOAD, stream=True)
        assert code2 == 200 and b"Hello" in body2 and b"upstream" in body2 and b"[DONE]" in body2
        assert box["n"] == 1                                            # upstream NOT hit on playback

    async def test_playback_miss_returns_504(self):
        """A request with no recorded match fails hard with HTTP 504 in playback mode."""
        pb = ProxyState(mode=ProxyState.MODE_PLAYBACK,
                        cassette=Cassette(str(self.tmp_path / "empty.json"), use_multi_mode=False))
        pb_url = self.start_app(RecordPlaybackLlmServer.build_app(pb))
        code, body = await ProxyTestClient.post(pb_url + ProxyTestClient.CHAT_PATH, ProxyTestClient.PAYLOAD)
        assert code == 504 and b"no recorded response" in body

    async def test_multi_response_roundrobin(self):
        """Multi-response records distinct variants and plays them back round-robin."""
        box = {"n": 0}
        upstream = self.start_app(
            tornado.web.Application([(ProxyTestClient.CHAT_PATH, CountingUpstream, {"box": box})]))
        path = str(self.tmp_path / "c.json")

        rec = ProxyState(mode=ProxyState.MODE_RECORD, cassette=Cassette(path, use_multi_mode=True),
                         upstream=ProxyTestClient.upstream_client(upstream), multi_response=True)
        rec_url = self.start_app(RecordPlaybackLlmServer.build_app(rec))
        for _ in range(3):
            await ProxyTestClient.post(rec_url + ProxyTestClient.CHAT_PATH, ProxyTestClient.PAYLOAD)
        assert len(list(Cassette(path, use_multi_mode=True).entries.values())[0]["responses"]) == 3

        pb = ProxyState(mode=ProxyState.MODE_PLAYBACK, cassette=Cassette(path, use_multi_mode=True),
                        multi_response=True)
        pb_url = self.start_app(RecordPlaybackLlmServer.build_app(pb))
        seen = [ProxyTestClient.content((await ProxyTestClient.post(
            pb_url + ProxyTestClient.CHAT_PATH, ProxyTestClient.PAYLOAD))[1]) for _ in range(4)]
        assert seen == ["resp-1", "resp-2", "resp-3", "resp-1"]         # round-robin with wrap

    async def test_hybrid_records_on_miss_then_hits(self):
        """Hybrid fetches+records on a miss, then serves the recorded response on a hit."""
        box = {"n": 0}
        upstream = self.start_app(
            tornado.web.Application([(ProxyTestClient.CHAT_PATH, CountingUpstream, {"box": box})]))
        path = str(self.tmp_path / "c.json")

        state = ProxyState(mode=ProxyState.MODE_HYBRID, cassette=Cassette(path, use_multi_mode=False),
                           upstream=ProxyTestClient.upstream_client(upstream))
        url = self.start_app(RecordPlaybackLlmServer.build_app(state))

        _, first = await ProxyTestClient.post(url + ProxyTestClient.CHAT_PATH, ProxyTestClient.PAYLOAD)
        assert box["n"] == 1                                           # miss -> fetch + record
        _, second = await ProxyTestClient.post(url + ProxyTestClient.CHAT_PATH, ProxyTestClient.PAYLOAD)
        assert box["n"] == 1                                           # hit -> upstream NOT hit again
        assert ProxyTestClient.content(first) == ProxyTestClient.content(second)
        assert len(Cassette(path, use_multi_mode=False)) == 1

    async def test_hybrid_miss_without_upstream_returns_504(self):
        """Hybrid with no upstream behaves like plain playback: a miss is a 504."""
        state = ProxyState(mode=ProxyState.MODE_HYBRID,
                           cassette=Cassette(str(self.tmp_path / "empty.json"), use_multi_mode=False), upstream=None)
        url = self.start_app(RecordPlaybackLlmServer.build_app(state))
        code, _ = await ProxyTestClient.post(url + ProxyTestClient.CHAT_PATH, ProxyTestClient.PAYLOAD)
        assert code == 504

    async def test_non_2xx_relayed_but_not_recorded(self):
        """A non-2xx upstream response is relayed to the caller but never cached."""
        upstream = self.start_app(tornado.web.Application([(ProxyTestClient.CHAT_PATH, RateLimitedUpstream)]))
        path = str(self.tmp_path / "c.json")
        state = ProxyState(mode=ProxyState.MODE_RECORD, cassette=Cassette(path, use_multi_mode=False),
                           upstream=ProxyTestClient.upstream_client(upstream))
        url = self.start_app(RecordPlaybackLlmServer.build_app(state))

        code, body = await ProxyTestClient.post(url + ProxyTestClient.CHAT_PATH, ProxyTestClient.PAYLOAD)
        assert code == 429 and b"Too Many Requests" in body           # relayed to caller
        assert len(Cassette(path, use_multi_mode=False)) == 0         # not recorded
        assert not os.path.exists(path)                              # nothing written at all

    async def test_stream_non_2xx_relayed_with_correct_status(self):
        """
        A streamed request whose upstream returns a non-2xx must be relayed with
        the real status (not a bogus 200 text/event-stream) and not recorded.
        """
        upstream = self.start_app(tornado.web.Application([(ProxyTestClient.CHAT_PATH, RateLimitedUpstream)]))
        path = str(self.tmp_path / "c.json")
        state = ProxyState(mode=ProxyState.MODE_RECORD, cassette=Cassette(path, use_multi_mode=False),
                           upstream=ProxyTestClient.upstream_client(upstream))
        url = self.start_app(RecordPlaybackLlmServer.build_app(state))

        code, body = await ProxyTestClient.post(url + ProxyTestClient.CHAT_PATH, ProxyTestClient.PAYLOAD, stream=True)
        assert code == 429 and b"Too Many Requests" in body           # real status, not 200
        assert len(Cassette(path, use_multi_mode=False)) == 0         # not recorded
