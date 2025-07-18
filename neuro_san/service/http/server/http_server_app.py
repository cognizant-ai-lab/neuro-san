
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
from typing import Any
from typing import Dict
from typing import List

import time

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
    SHUTDOWN_TIMEOUT_SECONDS: int = 30

    def __init__(self, handlers,
                 requests_limit: int,
                 logger: EventLoopLogger,
                 forwarded_request_metadata: List[str]):
        """
        Constructor:
        :param handlers: list of request handlers
        :param requests_limit: limit for number of requests we can execute
        :param logger: logger to use
        :param forwarded_request_metadata: list of client metadata keys
        """
        # Call the base constructor
        super().__init__(handlers=handlers)
        self.total: int = 0
        self.num_processing: int = 0
        self.requests_stats: Dict[str, int] = {}
        self.requests_limit: int = requests_limit
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

    def start_client_request(self, metadata: Dict[str, Any], caller: str):
        """
        Register start of client request.
        :param metadata: request metadata
        :param caller: name of request client to be used for stats
        """
        self.logger.info(metadata, "Start %s", caller)
        with self.lock:
            self.num_processing += 1
            self.requests_stats[caller] = self.requests_stats.get(caller, 0) + 1

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
        self.logger.info(metadata, "Finish %s", caller)
        if get_stats:
            self.logger.info(metadata, "Stats: %s", self.get_stats())
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
