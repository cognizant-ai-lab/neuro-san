
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

from os import environ

from neuro_san.interfaces.usage_logger import UsageLogger
from neuro_san.internals.utils.resolver_util import ResolverUtil
from neuro_san.service.usage.wrapped_usage_logger import WrappedUsageLogger


class UsageLoggerFactory:
    """
    Implementation of the UsageLogger interface that merely spits out
    usage stats to the logger.
    """

    @staticmethod
    def create_usage_logger(self) -> WrappedUsageLogger:
        """
        Reads the server environment variables to create a UsageLogger instance.

        :return: A WrappedUsageLogger that wraps the class referred to by the
                AGENT_USAGE_LOGGER env var.  Can throw an exception
                if there are problems creating the class referenced by the env var.
        """
        usage_logger_class_name: str = environ.get("AGENT_USAGE_LOGGER")
        usage_logger: UsageLogger = ResolverUtil.create_instance(usage_logger_class_name,
                                                                 "AGENT_USAGE_LOGGER env var",
                                                                 UsageLogger)
        wrapped: WrappedUsageLogger = WrappedUsageLogger(usage_logger)
        return wrapped
