
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

from neuro_san.interfaces.usage_logger import UsageLogger


class NullUsageLogger(UsageLogger):
    """
    Implementation of the UsageLogger interface that does nothing.
    """

    def log_usage(self, token_dict: Dict[str, Any], request_metadata: Dict[str, Any]):
        """
        Logs the token usage for external capture.

        :param token_dict: A dictionary that describes overall token usage for a completed request.

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
