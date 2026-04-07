
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
from typing import Tuple

import time

from http import HTTPStatus

from threading import Lock
from threading import Thread

from tornado.web import Application
from tornado.web import ErrorHandler
from tornado.ioloop import IOLoop

from neuro_san.service.http.handlers.base_request_handler import BaseRequestHandler
from neuro_san.service.interfaces.event_loop_logger import EventLoopLogger


class HttpServerApp(Application):
    """
    Class provides customized Tornado application for neuro-san service -
    with redefined internal logger so we can include custom request metadata.
    """
    # pylint: disable=too-many-instance-attributes
    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    SHUTDOWN_TIMEOUT_SECONDS: int = 30

    def __init__(self, handlers,
                 requests_limit: int,
                 concurrent_requests_limit: int,
                 logger: EventLoopLogger,
                 forwarded_request_metadata: List[str]):
        """
        Constructor:
        :param handlers: list of request handlers
        :param requests_limit: limit for number of requests we can execute
        :param concurrent_requests_limit: limit for number of concurrent requests we can execute
        :param logger: logger to use
        :param forwarded_request_metadata: list of client metadata keys
        """
        # Call the base constructor
        super().__init__(handlers=handlers)
        self.total: int = 0
        self.num_processing: int = 0
        self.requests_stats: Dict[str, int] = {}
        self.requests_limit: int = requests_limit
        self.concurrent_requests_limit: int = concurrent_requests_limit
        self.logger: EventLoopLogger = logger
        self.forwarded_request_metadata: List[str] = forwarded_request_metadata
        self.serving: bool = True
        self.shutdown_initiated: bool = False
        self.lock: Lock = Lock()
        self.shutdown_thread = None

    def is_serving(self) -> bool:
        """
        Return True if server continues to serve requests,
        False otherwise.
        """
        return self.serving

    def try_start_client_request(self, metadata: Dict[str, Any], caller: str) -> Tuple[HTTPStatus, str]:
        """
        Try to start new client request and register it if successful.
        :param metadata: request metadata
        :param caller: name of request client to be used for stats
        :return: A tuple of (HTTP status code, error message).
                 If the request can be started,
                 the status code will be HTTPStatus.OK and error message will be empty.
                 Otherwise, some error status code will be returned and error message will contain the reason.
        """
        if not self.serving:
            return HTTPStatus.SERVICE_UNAVAILABLE, "Server is shutting down"
        with self.lock:
            # num_processing is the number of currently served requests:
            if 0 < self.concurrent_requests_limit <= self.num_processing:
                return HTTPStatus.SERVICE_UNAVAILABLE, "Too many concurrent requests"
            self.num_processing += 1
            self.requests_stats[caller] = self.requests_stats.get(caller, 0) + 1
        self.logger.info(metadata, "Start %s", caller)
        return HTTPStatus.OK, ""

    def finish_client_request(self, metadata: Dict[str, Any],
                              caller: str, get_stats: bool = False):
        """
        Register finishing of client request.
        :param metadata: request metadata
        :param caller: name of request client to be used for stats
        :param get_stats: True if we need to log requests statistics,
                          False otherwise.
        """
        limit_reached: bool = False
        with self.lock:
            self.num_processing -= 1
            self.total += 1
            limit_reached = 0 <= self.requests_limit < self.total
            if get_stats:
                stats_data: Dict[str, Any] = self.get_stats()
        self.logger.info(metadata, "Finish %s", caller)
        if get_stats:
            self.logger.info(metadata, "Stats: %s", stats_data)
        # Now check if we reached requests limit:
        if limit_reached:
            self.serving = False
            self.initiate_shutdown()

    def do_shutdown(self, loop):
        """
        Poll for state with no executing requests
        or till we hit timeout:
        :param loop: event loop to stop
        """
        time_waited_seconds: int = 0
        wait_period_seconds = 2
        while time_waited_seconds < self.SHUTDOWN_TIMEOUT_SECONDS:
            if self.num_processing <= 0:
                break
            time.sleep(wait_period_seconds)
            time_waited_seconds += wait_period_seconds
        self.logger.info({}, "SERVER EXITING")
        self.stop_server(loop)

    def stop_server(self, loop):
        """
        Stop Tornado server event loop
        :param loop: event loop to stop
        """
        loop.add_callback(loop.stop)

    def initiate_shutdown(self):
        """
        Initiate server shutdown process
        """
        if self.shutdown_initiated:
            return
        self.shutdown_initiated = True
        self.logger.info({}, "Server request limit %d reached. Shutting down...", self.requests_limit)
        self.shutdown_thread = Thread(target=self.do_shutdown, args=(IOLoop.current(),), daemon=True)
        self.shutdown_thread.start()

    def get_stats(self) -> str:
        """
        Construct a string with current server requests statistics.
        """
        stats_dict: Dict[str, Any] = {
            "NumProcessing": self.num_processing,
            "Total": self.total
        }
        stats_dict.update(self.requests_stats)
        return str(stats_dict)

    def log_request(self, handler):
        if isinstance(handler, BaseRequestHandler):
            request = handler.request
            metadata: Dict[str, Any] = handler.get_metadata()
            status = handler.get_status()
            duration = 1000 * request.request_time()  # in milliseconds
            # handler.logger is our custom HttpLogger
            handler.logger.info(metadata, "%d %s %s (%s) %.2fms",
                                status, request.method, request.uri, request.remote_ip, duration)
        elif isinstance(handler, ErrorHandler):
            request = handler.request
            metadata: Dict[str, Any] =\
                BaseRequestHandler.get_request_metadata(request, self.forwarded_request_metadata)
            status = handler.get_status()
            duration = 1000 * request.request_time()  # in milliseconds
            # handler.logger is our custom HttpLogger
            self.logger.error(metadata, "%d %s %s (%s) %.2fms",
                              status, request.method, request.uri, request.remote_ip, duration)
        else:
            # Fall back to base request logger:
            super().log_request(handler)
