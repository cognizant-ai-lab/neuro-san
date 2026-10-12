
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
from types import ModuleType
from typing import Any
from unittest import TestCase

import openai

from openai import DefaultAsyncHttpxClient

from neuro_san.internals.run_context.langchain.util.openai_httpx import OpenAIHttpx


class TestOpenAIHttpx(TestCase):
    """
    Tests for OpenAIHttpx, which names the httpx library behind the installed OpenAI SDK.
    """

    def test_module_is_the_library_behind_the_sdk_client(self) -> None:
        """
        The module is httpx or httpx2, and it is the one the SDK's own default client derives from.
        """
        module: ModuleType = OpenAIHttpx.module()
        self.assertIn(module.__name__, ("httpx", "httpx2"))
        self.assertTrue(issubclass(DefaultAsyncHttpxClient, module.AsyncClient))

    def test_module_follows_the_sdk_major_version(self) -> None:
        """
        openai 2.x is built on httpx and openai 3.x on httpx2.
        """
        major: int = int(openai.__version__.split(".", maxsplit=1)[0])
        expected: str = "httpx2" if major >= 3 else "httpx"
        self.assertEqual(OpenAIHttpx.module().__name__, expected)

    def test_module_has_what_the_policies_and_tests_build(self) -> None:
        """
        The names the policies and the tests reach through the module exist on it.
        """
        module: ModuleType = OpenAIHttpx.module()
        for name in ("AsyncClient", "Limits", "Timeout", "MockTransport", "Request", "Response"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(module, name))

    def test_limits_come_from_the_same_library(self) -> None:
        """
        limits() builds a Limits of the module, carrying the values given; None means no limit.
        """
        limits: Any = OpenAIHttpx.limits(max_connections=None, max_keepalive_connections=None)
        self.assertIsInstance(limits, OpenAIHttpx.module().Limits)
        self.assertIsNone(limits.max_connections)
        self.assertIsNone(limits.max_keepalive_connections)

        bounded: Any = OpenAIHttpx.limits(max_connections=8, max_keepalive_connections=2)
        self.assertEqual(bounded.max_connections, 8)
        self.assertEqual(bounded.max_keepalive_connections, 2)
