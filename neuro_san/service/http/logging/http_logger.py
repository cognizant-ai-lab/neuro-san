
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
from typing import Sequence

import copy
import logging
import pathlib

from leaf_server_common.logging.logging_setup import setup_logging

from neuro_san.service.http.logging.log_context_filter import LogContextFilter
from neuro_san.service.interfaces.event_loop_logger import EventLoopLogger


class HttpLogger(EventLoopLogger):
    """
    Custom logger class for use by Http server.
    """

    HTTP_LOGGER_NAME: str = "HttpServer"

    def __init__(self, forwarded_metadata: Sequence[str],
                 logging_config: Dict[str, Any]):
        """
        Constructor

        :param forwarded_metadata: list of metadata keys to be forwarded
        :param logging_config: logging configuration dictionary
        """
        # Initialize minimal metadata dictionary to contain some value
        # for each metadata key we expect to be used.
        self.base_metadata: Dict[str, Any] = {}
        for key in forwarded_metadata:
            self.base_metadata[key] = "None"
        self.base_metadata["source"] = HttpLogger.HTTP_LOGGER_NAME
        LogContextFilter.set_log_context()
        self.setup_logging(logging_config)
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

    def setup_logging(self, logging_config: Dict[str, Any]):
        """
        Setup logging from configuration file.

        :param logging_config: logging configuration dictionary
        """
        # Need to initialize the forwarded metadata default values before our first
        # call to a logger.
        current_dir: str = pathlib.Path(__file__).parent.parent.resolve()
        setup_logging(HttpLogger.HTTP_LOGGER_NAME,
                      default_log_dir=current_dir,
                      log_level_env="AGENT_SERVICE_LOG_LEVEL",
                      extra_logging_fields_defaults=self.base_metadata,
                      logging_config=logging_config)

        # This module within openai library can be quite chatty w/rt http requests
        logging.getLogger("httpx").setLevel(logging.WARNING)

    def prepare_filter(self, metadata: Dict[str, Any]):
        """
        Prepare logging filter using request metadata,
        """
        use_metadata: Dict[str, Any] = copy.copy(self.base_metadata)
        use_metadata.update(metadata)
        LogContextFilter.log_context.set(use_metadata)
