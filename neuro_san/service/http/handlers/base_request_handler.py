
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
from typing import List
from typing import Optional

from http import HTTPStatus

import json
import os
import asyncio

import tornado
from tornado.web import RequestHandler

from leaf_common.utils.async_atomic_counter import AsyncAtomicCounter
from neuro_san.internals.interfaces.storage_class import StorageClass
from neuro_san.internals.reservations.agent_reservation import AgentReservation
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.internals.network_providers.expiring_agent_network_storage import ExpiringAgentNetworkStorage
from neuro_san.service.generic.async_agent_service import AsyncAgentService
from neuro_san.service.generic.async_agent_service_provider import AsyncAgentServiceProvider
from neuro_san.service.interfaces.agent_authorizer import AgentAuthorizer
from neuro_san.service.utils.request_util import RequestUtil
from neuro_san.service.utils.server_context import ServerContext
from neuro_san.service.http.logging.http_logger import HttpLogger


class BaseRequestHandler(RequestHandler):
    """
    Abstract handler class for neuro-san API calls.
    Provides logic to inject neuro-san service specific data
    into local handler context.
    """
    request_id_counter: AsyncAtomicCounter = AsyncAtomicCounter()

    # pylint: disable=attribute-defined-outside-init
    def initialize(self, **kwargs):
        """
        This method is called by Tornado framework to allow
        injecting service-specific data into local handler context.
        :param kwargs: dictionary of named parameters, including:
            "agent_policy" - abstract policy for agent requests;
            "forwarded_request_metadata" - list of request metadata keys to forward;
            "openapi_service_spec" - OpenAPI service spec dictionary;
            "server_context" - ServerContext instance for this server.
            "logging_config" - logging configuration dictionary
        """
        # Set up local members from kwargs dictionary passed in:
        self.agent_policy: AgentAuthorizer = kwargs.pop("agent_policy", None)
        self.forwarded_request_metadata: List[str] = kwargs.pop("forwarded_request_metadata", [])
        self.openapi_service_spec: Dict[str, Any] = kwargs.pop("openapi_service_spec", None)
        self.server_context: ServerContext = kwargs.pop("server_context", None)
        logging_config: Dict[str, Any] = kwargs.pop("logging_config", None)

        self.logger = HttpLogger(self.forwarded_request_metadata, logging_config)
        self.show_absent: bool = os.environ.get("SHOW_ABSENT_METADATA") is not None
        self.request_id: int = 0

        if os.environ.get("AGENT_ALLOW_CORS_HEADERS") is not None:
            self.set_header("Access-Control-Allow-Origin", "*")
            self.set_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            headers: str = "Content-Type, Transfer-Encoding"
            metadata_headers: str = ", ".join(self.forwarded_request_metadata)
            if len(metadata_headers) > 0:
                headers += f", {metadata_headers}"
            # Set all allowed headers:
            self.set_header("Access-Control-Allow-Headers", headers)

    def get_metadata(self) -> Dict[str, Any]:
        """
        Extract user metadata defined by self.forwarded_request_metadata list
        from incoming request.
        :return: dictionary of user request metadata; possibly empty
        """
        metadata_dict: Dict[str, Any] =\
            BaseRequestHandler.get_request_metadata(
                self.request,
                self.forwarded_request_metadata,
                self.show_absent,
                self.logger)
        # Put in our own unique id so we have some way to track this request:
        user_request_id: str = metadata_dict.get("request_id", "None")
        if user_request_id == "None":
            metadata_dict["request_id"] = f"request-{self.request_id}"
        return metadata_dict

    @classmethod
    def get_request_metadata(cls, request,
                             forwarded_request_metadata: List[str],
                             show_absent: bool = False,
                             logger: HttpLogger = None
                             ) -> Dict[str, Any]:
        """
        Extract user metadata defined by forwarded_request_metadata list
        from incoming request.
        :param request: incoming http request
        :param forwarded_request_metadata: list of metadata keys
        :param show_absent: if True, will provide debug printout
               for all request metadata keys absent from incoming request headers;
               if False does nothing.
        :param logger: logger to use
        :return: dictionary of user request metadata; possibly empty
        """
        headers: Dict[str, Any] = request.headers
        result: Dict[str, Any] = {}
        for item_name in forwarded_request_metadata:
            if item_name in headers.keys():
                result[item_name] = headers[item_name]
            else:
                if show_absent and logger:
                    logger.warning({}, "MISSING METADATA VALUE: %s request %s", item_name, request.uri)
                result[item_name] = "None"
        return result

    async def get_service(self, agent_name: str, metadata: Dict[str, Any]) -> AsyncAgentService:
        """
        Get agent's AsyncAgentService for request execution
        :param agent_name: agent name
        :param metadata: metadata to be used for logging if necessary.
        :return: instance of AsyncAgentService if it is defined for this agent
                 None otherwise
        """
        is_authorized: bool = False
        service_provider: AsyncAgentServiceProvider = None
        is_authorized, service_provider = await self.agent_policy.allow_agent(agent_name, metadata)

        if not is_authorized:
            # Forbidden
            self.set_status(403)
            self.do_finish()
            return None

        if service_provider is not None:
            return service_provider.get_service()

        # Now, this could be a temporary network created outside of our service:
        # Does it look like a temporary network name?
        if AgentReservation.is_reservation_name(agent_name):
            # Get temporary network storage:
            network_storage_dict: Dict[str, AgentNetworkStorage] = self.server_context.get_network_storage_dict()
            temp_storage: AgentNetworkStorage = network_storage_dict.get(StorageClass.TEMP, None)
            if temp_storage is None or not isinstance(temp_storage, ExpiringAgentNetworkStorage):
                self.set_status(500)
                self.logger.error(metadata, "error: Temporary network storage is not properly configured.")
                self.do_finish()
                return None
            # This call will trigger temp network lookup in external storage
            # and if found, it will be registered in our service
            # and become available for future requests until it expires.
            # Note that "network_provider" result is not used directly here,
            # but the call is necessary to trigger the "side effect" of lookup and registration of temp network.
            # We delegate call execution to a thread to avoid blocking server event loop
            # with potentially slow external storage access.
            network_provider = await asyncio.to_thread(temp_storage.get_agent_network_provider, agent_name)
            if network_provider is not None:
                # Now that our service is aware of this temp network,
                # we can query our policy again,
                # and we already know that this agent has been authorized:
                _, service_provider = await self.agent_policy.allow_agent(agent_name, metadata)
                # If service provider is still None,
                # that means something went very wrong - bail out:
                if service_provider is not None:
                    return service_provider.get_service()

        # Nothing worked - so we report resource not found
        self.set_status(404)
        self.logger.error(metadata, "error: Invalid request path %s", self.request.path)
        self.do_finish()
        return None

    def process_exception(self, exc: Exception):
        """
        Process exception raised during request handling
        """
        if exc is None:
            return
        if isinstance(exc, json.JSONDecodeError):
            # Handle invalid JSON input
            self.set_status(HTTPStatus.BAD_REQUEST)
            self.write({"error": "Invalid JSON format"})
            self.logger.error(self.get_metadata(), "error: Invalid JSON format")
            return

        # General exception case:
        self.set_status(HTTPStatus.INTERNAL_SERVER_ERROR)
        self.write({"error": "Internal server error"})
        self.logger.error(self.get_metadata(), "Internal server error: %s", str(exc))

    def data_received(self, chunk):
        """
        Method overrides abstract method of RequestHandler
        with no-op implementation.
        """
        return

    # Tornado can handle both syns and async versions of "prepare" method
    # pylint: disable=invalid-overridden-method
    async def prepare(self):
        if not self.application.is_serving():
            self.set_status(HTTPStatus.SERVICE_UNAVAILABLE)
            self.write({"error": "Server is shutting down"})
            self.logger.error(self.get_metadata(), "Server is shutting down")
            self.do_finish()
            return

        # Get unique request id in case we will need it:
        self.request_id = await self.request_id_counter.increment()

        self.logger.debug(self.get_metadata(), f"[REQUEST RECEIVED] {self.request.method} {self.request.uri}")

    def do_finish(self, status_code: HTTPStatus = HTTPStatus.OK, err_message: Optional[str] = None):
        """
        Wrapper for finish() call,
        with check for result status code and error message to write out if necessary,
        Also check for closed client connection.
        :param status_code: HTTP status code to set for response; default is 200 OK
        :param err_message: error message to write out in response body in case of error;
            default is None, which means no error message will be written out.
        """
        if status_code != HTTPStatus.OK:
            self.set_status(status_code)
            if err_message:
                # HTML-escape the error message defensively, since some err_message
                # values may originate from user-controlled input.
                self.write({"error": RequestUtil.safe_message(err_message)})
        try:
            self.finish()
        except tornado.iostream.StreamClosedError:
            self.logger.warning(self.get_metadata(), "Finish: client closed connection unexpectedly.")

    async def do_flush(self) -> bool:
        """
        Wrapper for flush() call
        with check for closed client connection.
        """
        try:
            await self.flush()
            return True
        except tornado.iostream.StreamClosedError:
            self.logger.warning(self.get_metadata(), "Flush: client closed connection unexpectedly.")
            return False

    async def options(self, *_args, **_kwargs):
        """
        Handles OPTIONS requests for CORS support
        """
        # No body needed. Tornado will return a 204 No Content by default
        self.set_status(HTTPStatus.NO_CONTENT)
        self.do_finish()
