
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
See comments in class description
"""

import logging
from typing import Any
from typing import Dict
from threading import Lock
import grpc


class DynamicAgentRouter(grpc.GenericRpcHandler):
    """
    Class maintains a dynamic map of gRPC services exposed by a server.
    Each gRPC service represents an agent available to clients.
    Instance of this class is also a generic gRPC handler,
    routing incoming gRPC request to appropriate API method handler
    depending on service name.
    """

    instance = None

    def __init__(self):
        """
        Constructor.
        """
        self.agents_table: Dict[str, Any] = {}
        self.table_lock: Lock = Lock()
        self.logger = logging.getLogger(self.__class__.__name__)

    def add_service(self, service_name: str, handlers: Dict[str, Any]):
        """
        Add service with its API handlers to this router.
        :param service_name: gRPC-formatted service name;
        :param handlers: table of API handlers to register for this service.
        """
        with self.table_lock:
            self.agents_table[service_name] = handlers
        self.logger.info("Added service handlers for %s", service_name)

    def remove_service(self, service_name: str):
        """
        Remove service from this router.
        :param service_name: gRPC-formatted service name;
        """
        with self.table_lock:
            self.agents_table.pop(service_name, None)
        self.logger.info("Removed service handlers for %s", service_name)

    def service(self, handler_call_details: grpc.HandlerCallDetails):
        """
        Service incoming gRPC request.
        :param handler_call_details: gRPC incoming call details.
        :return: gRPC method handler for this call. This handler will be invoked
            elsewhere by gRPC machinery.
        """
        full_method: str = "unknown"
        try:
            full_method = handler_call_details.method  # e.g. "/my.Service/SomeMethod"
            _, service_name, method_name = full_method.split("/", 2)
            with self.table_lock:
                method_handlers = self.agents_table.get(service_name, None)
            if method_handlers:
                return method_handlers.get(method_name, None)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self.logger.error("Failed to execute %s - %s", full_method, str(exc))
        # Request not handled, in this case gRPC stack will raise UNIMPLEMENTED exception
        # and http server will return error code 500 with details: "Method not found!"
        return None
