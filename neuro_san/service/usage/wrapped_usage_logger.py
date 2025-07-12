
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

from typing import Any
from typing import Dict
from typing import List

from asyncio import run
from os import environ

from neuro_san.interfaces.usage_logger import UsageLogger


class WrappedUsageLogger(UsageLogger):
    """
    Implementation of the UsageLogger interface that wraps another UsageLogger
    and whose log_usage method makes sure sloppier inputs adhere better to the
    UsageLogger contract.
    """

    def __init__(self, wrapped: UsageLogger):
        """
        Constructor

        :param wrapped: The UsageLogger instance that is wrapped.
                        Can be None and log_usage() will handle that.
        """
        self.wrapped: UsageLogger = wrapped

    async def log_usage(self, token_dict: Dict[str, Any], request_metadata: Dict[str, Any]):
        """
        Logs the token usage for external capture.

        :param token_dict: A dictionary that describes overall token usage for a completed request.

                For each class of LLM (more or less equivalent to an LLM provider), there will
                be one key whose value is a dictionary with some other keys:

                Relevant keys include:
                    "completion_tokens" - Integer number of tokens generated in response to LLM input
                    "prompt_tokens" - Integer number of tokens that provide input to an LLM
                    "time_taken_in_seconds" - Float describing the total wall-clock time taken for the request.
                    "total_cost" -  An estimation of the cost in USD of the request.
                                    This number is to be taken with a grain of salt, as these estimations
                                    can come from model costs from libraries instead of directly from
                                    providers.
                    "total_tokens" - Total tokens used for the request.

                More keys can appear, but should not be counted on.
                The ones listed above contain potentially salient information for usage logging purposes.

        :param request_metadata: A dictionary of filtered request metadata whose keys contain
                identifying information for the usage log.
        """
        if self.wrapped is None:
            # Nothing to report
            return

        if token_dict is None:
            # Nothing to report
            return

        compliant_token_dict: Dict[str, Any] = self.make_compliant_token_dict(token_dict)
        minimal_metadata: Dict[str, Any] = self.minimize_metadata(request_metadata)

        await self.wrapped.log_usage(compliant_token_dict, minimal_metadata)

    def synchronous_log_usage(self, token_dict: Dict[str, Any], request_metadata: Dict[str, Any]):
        """
        Logs the token usage for external capture.
        See comments for log_usage() above.
        """
        run(self.log_usage(token_dict, request_metadata))

    def make_compliant_token_dict(self, token_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        :param token_dict: The token dictionary to make compliant if it is not already
        :return: A token dictionary compliant to the UsageLogger interface
        """
        compliant: Dict[str, Any] = token_dict

        if "total_tokens" in token_dict.keys():
            # We have a raw token dictionary without any attribution to the LLM.
            # Make the dictionary compliant
            compliant = {
                "all": token_dict
            }

        return compliant

    def minimize_metadata(self, request_metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        :param request_metadata: The raw request metadata dictionary that could easily contain
                    more keys than we want to send to the UsageLogger.
        :return: A minimized dictionary that only sends the keys we need to the UsageLogger.
                The idea is that this prevents the UsageLogger from getting potentially
                sensitive information it shouldn't really have.

                If the requested keys in the metadata are not there, they will also not appear
                in the returned minimized dictionary.
        """
        minimized: Dict[str, Any] = {}

        # Try getting the value from the more specific env var before falling back to the
        # other env var.
        keys_string: str = environ.get("AGENT_USAGE_LOGGER_METADATA",
                                       environ.get("AGENT_FORWARDED_REQUEST_METADATA"))

        if keys_string is None or len(keys_string) == 0:
            return minimized

        keys: List[str] = keys_string.split(" ")
        for key in keys:
            if key is None or len(key) == 0:
                # Skip any empty key split from the list. Allows for multi-spaces.
                continue
            value: Any = request_metadata.get(key)
            if value is not None:
                minimized[key] = value

        return minimized
