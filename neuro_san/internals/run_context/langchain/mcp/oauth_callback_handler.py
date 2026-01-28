
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

from asyncio import Future
from logging import Logger
from logging import getLogger
from typing import List
from typing import Optional
from urllib.parse import urlparse
from urllib.parse import ParseResult
import webbrowser

from aiohttp.web import Application
from aiohttp.web import AppRunner
from aiohttp.web import Request
from aiohttp.web import Response
from aiohttp.web import TCPSite


# pylint: disable=too-many-instance-attributes
class OauthCallbackHandler:
    """
    Handles OAuth callbacks by running a local HTTP server.
    Automatically opens browser and captures the redirect.
    """

    def __init__(self, port: int = 3000):
        """ Constructor """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.port = port
        self.redirect_uri = f"http://localhost:{port}/callback"
        self.auth_code: Optional[str] = None
        self.state: Optional[str] = None
        self.error: Optional[str] = None
        self.app: Optional[Application] = None
        self.runner: Optional[AppRunner] = None
        self.site: Optional[TCPSite] = None
        self._callback_future: Optional[Future] = None

    async def _handle_callback(self, request: Request) -> Response:
        """
        Handle OAuth callback request.

        :param request: HTTP request for callback to return the authorization code.
        """
        params = request.query
        self.auth_code = params.get("code")
        self.state = params.get("state")
        self.error = params.get("error")

        if self.error:
            html = f"""
            <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
                <h1>Authentication Failed</h1>
                <p>Error: {self.error}</p>
                <p>You can close this window.</p>
            </body></html>
            """
        else:
            html = """
            <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
                <h1>Authentication Successful!</h1>
                <p>You can close this window and return to your application.</p>
            </body></html>
            """

        # Signal that callback was received
        if self._callback_future and not self._callback_future.done():
            self._callback_future.set_result(True)

        return Response(text=html, content_type="text/html")

    async def start_server(self):
        """Start the callback server."""
        self.app = Application()
        self.app.router.add_get("/callback", self._handle_callback)

        self.runner = AppRunner(self.app)
        await self.runner.setup()

        self.site = TCPSite(self.runner, "localhost", self.port)
        await self.site.start()

        self.logger.info("✓ Local callback server started on %s", self.redirect_uri)

    async def stop_server(self):
        """Stop the callback server."""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        self.logger.info("✓ Callback server stopped")

    async def handle_redirect(self, url: str) -> None:
        """
        Open browser to OAuth URL.

        :param url: URL for authorization endpoint and query parameters.
        """
        self.logger.info("="*70)
        self.logger.info("🔐 OPENING BROWSER FOR AUTHENTICATION")
        self.logger.info("="*70)
        parsed: ParseResult = urlparse(url)
        auth_endpoint: str = parsed.scheme + "://" + parsed.netloc + parsed.path
        self.logger.info("Authorization endpoint: %s", auth_endpoint)
        query_params: List[str] = []
        for param in parsed.query.split("&"):
            query_params.append(param.split("=")[0])
        self.logger.info("Query parameters: %s", query_params)
        webbrowser.open(url)

    async def wait_for_callback(self) -> tuple[str, Optional[str]]:
        """Wait for OAuth callback and return (code, state)."""
        self.logger.info("⏳ Waiting for authentication callback...")

        # Create a future to wait for callback
        self._callback_future = Future()

        # Wait for callback
        await self._callback_future

        if self.error:
            raise ValueError(f"OAuth error: {self.error}")

        if not self.auth_code:
            raise ValueError("No authorization code received")

        self.logger.info("✓ Authentication callback received")
        return self.auth_code, self.state
