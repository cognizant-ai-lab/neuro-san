
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

import contextvars
import logging


class LogContextFilter(logging.Filter):
    """
    Custom logging filter for Http server.
    """

    def filter(self, record):
        """
        Logging filter: add key-value pairs from log_context
        to logging record to be used.
        """
        ctx = LogContextFilter.log_context.get()
        for key, value in ctx.items():
            setattr(record, key, value)
        return True

    @classmethod
    def set_log_context(cls):
        """
        Create log context class instance.
        """
        cls.log_context = contextvars.ContextVar("http_server_context", default={})
