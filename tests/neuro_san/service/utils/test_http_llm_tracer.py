
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
# pylint: disable=protected-access
from types import ModuleType
from typing import Any
from typing import Callable
from typing import List
from typing import Optional
from unittest import IsolatedAsyncioTestCase

from typing_extensions import override

from leaf_common.resolution.resolver import Resolver
from openai import DefaultAsyncHttpxClient

from neuro_san.internals.run_context.langchain.util.openai_httpx import OpenAIHttpx
from neuro_san.service.utils.http_llm_tracer import HttpxLlmTracer


class TestHttpxLlmTracer(IsolatedAsyncioTestCase):
    """
    Tests for HttpxLlmTracer, which hooks the AsyncClient of every installed httpx library.

    Requests go through the OpenAI SDK's own default client over a MockTransport, so the test
    exercises the library the SDK is built on without any network access.
    """

    LOGGER_NAME: str = "neuro_san.diagnostics.http_llm_trace"

    @override
    def setUp(self) -> None:
        """
        Undoes the tracer's class-level patching after each test, even one that fails part-way.
        """
        self.addCleanup(HttpxLlmTracer.uninstall)
        self.seen: List[str] = []

    async def _remember(self, request: Any) -> None:
        """
        A caller's own request hook: records the URL of each request sent.

        :param request: The Request being sent
        """
        self.seen.append(str(request.url))

    @staticmethod
    def _answer(request: Any) -> Any:
        """
        MockTransport handler answering every request with a small JSON body.

        The body is given as a stream, the way a real transport delivers it, so the client reads
        it through the response's iterator and the tracer's end event fires. A body passed as
        content or json would be preloaded and never iterated.

        :param request: The Request being sent, of the httpx library behind the SDK
        :return: A 200 Response of that library carrying a server request id header
        """
        sdk_httpx: ModuleType = OpenAIHttpx.module()
        return sdk_httpx.Response(200, stream=sdk_httpx.ByteStream(b'{"ok": true}'),
                                  headers={"x-request-id": "req-1", "content-type": "application/json"},
                                  request=request)

    @staticmethod
    def _installed_client_classes() -> List[type]:
        """
        Collects the AsyncClient class of each httpx library that is installed.

        :return: One class per installed library, httpx and/or httpx2
        """
        classes: List[type] = []
        resolver: Resolver = Resolver()
        for module_name in ("httpx", "httpx2"):
            module: Optional[ModuleType] = resolver.resolve_class_in_module(class_name=None, module_name=module_name,
                                                                            raise_if_not_found=False)
            if module is None:
                continue
            classes.append(module.AsyncClient)
        return classes

    async def test_sdk_client_requests_are_traced(self) -> None:
        """
        After install(), a request through the SDK's default client logs the out, in and end events.
        """
        HttpxLlmTracer.install()
        sdk_httpx: ModuleType = OpenAIHttpx.module()
        client: Any = DefaultAsyncHttpxClient(transport=sdk_httpx.MockTransport(self._answer))

        with self.assertLogs(self.LOGGER_NAME, level="INFO") as logs:
            response: Any = await client.post("https://api.openai.com/v1/responses", json={"input": "hi"})
            await response.aread()
        await client.aclose()

        output: str = "\n".join(logs.output)
        self.assertIn("http_llm_out", output)
        self.assertIn("http_llm_in", output)
        self.assertIn("http_llm_end", output)
        self.assertIn("req-1", output)
        self.assertEqual(response.status_code, 200)

    async def test_every_installed_httpx_library_is_patched(self) -> None:
        """
        install() patches the AsyncClient of each installed library, and uninstall() restores each.
        """
        classes: List[type] = self._installed_client_classes()
        originals: List[Callable[..., None]] = []
        for client_class in classes:
            originals.append(client_class.__init__)

        HttpxLlmTracer.install()
        for client_class in classes:
            with self.subTest(library=client_class.__module__):
                self.assertIs(client_class.__init__, HttpxLlmTracer._patched_httpx_init)

        HttpxLlmTracer.uninstall()
        for index, client_class in enumerate(classes):
            with self.subTest(library=client_class.__module__):
                self.assertIs(client_class.__init__, originals[index])

    async def test_existing_event_hooks_are_kept(self) -> None:
        """
        Hooks a caller passes to the client constructor still run alongside the tracer's.
        """
        HttpxLlmTracer.install()
        sdk_httpx: ModuleType = OpenAIHttpx.module()

        client: Any = sdk_httpx.AsyncClient(transport=sdk_httpx.MockTransport(self._answer),
                                            event_hooks={"request": [self._remember]})
        with self.assertLogs(self.LOGGER_NAME, level="INFO"):
            await client.get("https://api.openai.com/v1/models")
        await client.aclose()

        self.assertEqual(self.seen, ["https://api.openai.com/v1/models"])
