
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
from typing import Sequence

import copy
import logging
import pathlib

from leaf_server_common.logging.logging_setup import setup_logging

from neuro_san.service.http.logging.log_context_filter import LogContextFilter
from neuro_san.service.logging.event_loop_logger import EventLoopLogger


class HttpLogger(EventLoopLogger):
    """
    Custom logger class for use by Http server.
    """

    HTTP_LOGGER_NAME: str = "HttpServer"

    def __init__(self, forwarded_metadata: Sequence[str]):
        """
        Constructor
        """
        # Initialize minimal metadata dictionary to contain some value
        # for each metadata key we expect to be used.
        self.base_metadata: Dict[str, Any] = {}
        for key in forwarded_metadata:
            self.base_metadata[key] = "None"
        self.base_metadata["source"] = HttpLogger.HTTP_LOGGER_NAME
        LogContextFilter.set_log_context()
        self.setup_logging()
        # For our Http server, we have separate logging setup,
        # because things like "user_id" and "request_id"
        # can only be extracted and used on per-request basis.
        # Async Http server is single-threaded.
        self.logger = logging.getLogger(HttpLogger.HTTP_LOGGER_NAME)

    def info(self, metadata: Dict[str, Any], msg: str, *args):
        """
        "Info" logging method.
        Prepare logger filter with request-specific metadata
        and delegate logging to underlying standard Logger.
        """
        self.prepare_filter(metadata)
        self.logger.info(msg, *args)

    def warning(self, metadata: Dict[str, Any], msg: str, *args):
        """
        "Warning" logging method.
        Prepare logger filter with request-specific metadata
        and delegate logging to underlying standard Logger.
        """
        self.prepare_filter(metadata)
        self.logger.warning(msg, *args)

    def debug(self, metadata: Dict[str, Any], msg: str, *args):
        """
        "Debug" logging method.
        Prepare logger filter with request-specific metadata
        and delegate logging to underlying standard Logger.
        """
        self.prepare_filter(metadata)
        self.logger.debug(msg, *args)

    def error(self, metadata: Dict[str, Any], msg: str, *args):
        """
        "Error" logging method.
        Prepare logger filter with request-specific metadata
        and delegate logging to underlying standard Logger.
        """
        self.prepare_filter(metadata)
        self.logger.error(msg, *args)

    def setup_logging(self):
        """
        Setup logging from configuration file.
        """
        # Need to initialize the forwarded metadata default values before our first
        # call to a logger.
        current_dir: str = pathlib.Path(__file__).parent.parent.resolve()
        setup_logging(HttpLogger.HTTP_LOGGER_NAME, current_dir,
                      'AGENT_SERVICE_LOG_JSON',
                      'AGENT_SERVICE_LOG_LEVEL',
                      self.base_metadata)

        # This module within openai library can be quite chatty w/rt http requests
        logging.getLogger("httpx").setLevel(logging.WARNING)

    def prepare_filter(self, metadata: Dict[str, Any]):
        """
        Prepare logging filter using request metadata,
        """
        use_metadata: Dict[str, Any] = copy.copy(self.base_metadata)
        use_metadata.update(metadata)
        LogContextFilter.log_context.set(use_metadata)
