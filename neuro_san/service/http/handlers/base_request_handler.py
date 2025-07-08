
# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT
"""
See class comment for details
"""
import http
from typing import Any
from typing import Dict
from typing import List

import json
import os
import asyncio

import tornado
from tornado.web import RequestHandler

from neuro_san.internals.network_providers.service_agent_network_storage import ServiceAgentNetworkStorage
from neuro_san.service.http.interfaces.agent_authorizer import AgentAuthorizer
from neuro_san.service.http.interfaces.agents_updater import AgentsUpdater
from neuro_san.service.http.logging.http_logger import HttpLogger


class BaseRequestHandler(RequestHandler):
    """
    Abstract handler class for neuro-san API calls.
    Provides logic to inject neuro-san service specific data
    into local handler context.
    """

    request_id: int = 0

    # pylint: disable=attribute-defined-outside-init
    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def initialize(self,
                   agent_policy: AgentAuthorizer,
                   agents_updater: AgentsUpdater,
                   forwarded_request_metadata: List[str],
                   openapi_service_spec_path: str,
                   network_storage: ServiceAgentNetworkStorage):
        """
        This method is called by Tornado framework to allow
        injecting service-specific data into local handler context.
        :param agent_policy: abstract policy for agent requests
        :param agents_updater: abstract policy for updating
                               collection of agents being served
        :param forwarded_request_metadata: request metadata to forward.
        :param openapi_service_spec_path: file path to OpenAPI service spec.
        :param network_storage: A ServiceAgentNetworkStorage instance which keeps all
                                the AgentNetwork instances.
        """

        self.agent_policy = agent_policy
        self.agents_updater = agents_updater
        self.forwarded_request_metadata: List[str] = forwarded_request_metadata
        self.openapi_service_spec_path: str = openapi_service_spec_path
        self.logger = HttpLogger(forwarded_request_metadata)
        self.network_storage: ServiceAgentNetworkStorage = network_storage

        # Set default request_id for this request handler in case we will need it:
        BaseRequestHandler.request_id += 1

        if os.environ.get("AGENT_ALLOW_CORS_HEADERS") is not None:
            self.set_header("Access-Control-Allow-Origin", "*")
            self.set_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.set_header("Access-Control-Allow-Headers", "Content-Type, Transfer-Encoding, User_id")

    def get_metadata(self) -> Dict[str, Any]:
        """
        Extract user metadata defined by self.forwarded_request_metadata list
        from incoming request.
        :return: dictionary of user request metadata; possibly empty
        """
        headers: Dict[str, Any] = self.request.headers
        result: Dict[str, Any] = {}
        for item_name in self.forwarded_request_metadata:
            if item_name in headers.keys():
                result[item_name] = headers[item_name]
            elif item_name == "request_id":
                # Generate unique id so we have some way to track this request:
                result[item_name] = f"request-{BaseRequestHandler.request_id}"
            else:
                result[item_name] = "None"
        return result

    async def update_agents(self, metadata: Dict[str, Any]) -> bool:
        """
        Update internal agents table.
        :param metadata: metadata to be used for logging if necessary.
        :return: True if update was successful
                 False otherwise
        """
        try:
            self.agents_updater.update_agents(metadata=metadata)
            return True
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self.process_exception(exc)
            return False

    def process_exception(self, exc: Exception):
        """
        Process exception raised during request handling
        """
        if exc is None:
            return
        if isinstance(exc, json.JSONDecodeError):
            # Handle invalid JSON input
            self.set_status(400)
            self.write({"error": "Invalid JSON format"})
            self.logger.error(self.get_metadata(), "error: Invalid JSON format")
            return

        # General exception case:
        self.set_status(500)
        self.write({"error": "Internal server error"})
        self.logger.error(self.get_metadata(), "Internal server error: %s", str(exc))

    def data_received(self, chunk):
        """
        Method overrides abstract method of RequestHandler
        with no-op implementation.
        """
        return

    def prepare(self):
        if not self.application.is_serving():
            self.set_status(503)
            self.write({"error": "Server is shutting down"})
            self.logger.error(self.get_metadata(), "Server is shutting down")
            self.do_finish()
            return

        self.logger.info(self.get_metadata(), f"[REQUEST RECEIVED] {self.request.method} {self.request.uri}")

    def do_finish(self):
        """
        Wrapper for finish() call
        with check for closed client connection.
        """
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
            # What happens here: we have finished writing out one data item in our output stream,
            # and we have flushed Tornado output.
            # BUT: this does not guarantee in general that underlying TCP/IP transport
            # will flush its own buffers, so low-level buffering is still possible.
            # Result would be that several chat responses will be bunched together
            # and received by a client as one data piece.
            # If client is not ready for this, there will be problems.
            # SO: this real wall clock delay here helps to encourage underlying transport
            # to flush its own buffers - and we are good.
            # Duration of delay is speculative and maybe could be adjusted.
            # But best solution and reliable one: make client accept multiple data items
            # in one "get" request - as it should when dealing with streaming service.
            await asyncio.sleep(0.3)
            return True
        except tornado.iostream.StreamClosedError:
            self.logger.warning(self.get_metadata(), "Flush: client closed connection unexpectedly.")
            return False

    async def options(self, *_args, **_kwargs):
        """
        Handles OPTIONS requests for CORS support
        """
        # No body needed. Tornado will return a 204 No Content by default
        self.set_status(http.HTTPStatus.NO_CONTENT)
        self.do_finish()
