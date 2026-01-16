
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
See class comment for details
"""
from typing import Any
from typing import Dict

from http import HTTPStatus

import asyncio
import contextlib
import json
import tornado

from neuro_san.service.generic.async_agent_service import AsyncAgentService
from neuro_san.service.http.handlers.base_request_handler import BaseRequestHandler


class StreamingChatHandler(BaseRequestHandler):
    """
    Handler class for neuro-san streaming chat API call.
    """

    async def post(self, agent_name: str):
        """
        Implementation of POST request handler for streaming chat API call.
        """

        metadata: Dict[str, Any] = self.get_metadata()
        service: AsyncAgentService = await self.get_service(agent_name, metadata)
        if service is None:
            return

        self.application.start_client_request(metadata, f"{agent_name}/streaming_chat")
        # Set up request timeout if it is specified:
        request_timeout: float = service.get_request_timeout_seconds()
        if request_timeout <= 0.0:
            # For asyncio.timeout(), None means no timeout:
            request_timeout = None
        result_generator = None
        try:
            # Parse JSON body
            data = json.loads(self.request.body)

            # Set up headers for chunked response
            self.set_header("Content-Type", "application/json-lines")
            self.set_header("Transfer-Encoding", "chunked")
            # Flush headers immediately
            flush_ok: bool = await self.do_flush()
            if not flush_ok:
                # If we failed to flush our output,
                # most probably it's because connection is closed by a client.
                # Raise accordingly - we will handle this exception:
                raise tornado.iostream.StreamClosedError()

            async with asyncio.timeout(request_timeout):
                result_generator = service.streaming_chat(data, metadata)
                async for result_dict in result_generator:
                    result_str: str = json.dumps(result_dict) + "\n"
                    self.write(result_str)
                    flush_ok = await self.do_flush()
                    if not flush_ok:
                        # Raise exception to be handled as a general
                        # "stream abruptly closed" case:
                        raise tornado.iostream.StreamClosedError()

        except (asyncio.CancelledError, tornado.iostream.StreamClosedError):
            self.logger.info(metadata, "Request handler cancelled/stream closed.")
            # Re-raise as recommended
            raise

        except asyncio.TimeoutError:
            self.logger.info(metadata, "Chat request timeout for %s in %f seconds.", agent_name, request_timeout)
            # Recommended HTTP response code: Service Unavailable
            self.set_status(HTTPStatus.SERVICE_UNAVAILABLE)
            self.write({"error": "Request timeout"})

        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Suppress possible exceptions: they are of no interest here.
            with contextlib.suppress(Exception):
                self.process_exception(exc)

        finally:
            # We are done with response stream,
            # ensure generator is closed properly in any case:
            if result_generator is not None:
                with contextlib.suppress(Exception):
                    # It is possible we will call .aclose() twice
                    # on our result_generator - it is allowed and has no effect.
                    await result_generator.aclose()
            self.do_finish()
            self.application.finish_client_request(metadata, f"{agent_name}/streaming_chat", get_stats=True)
