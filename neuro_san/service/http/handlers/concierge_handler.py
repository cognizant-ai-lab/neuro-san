
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

from neuro_san.interfaces.concierge_session import ConciergeSession
from neuro_san.service.http.handlers.base_request_handler import BaseRequestHandler
from neuro_san.session.direct_concierge_session import DirectConciergeSession


class ConciergeHandler(BaseRequestHandler):
    """
    Handler class for neuro-san "concierge" API call.
    """

    def get(self):
        """
        Implementation of GET request handler for "concierge" API call.
        """
        metadata: Dict[str, Any] = self.get_metadata()
        self.application.start_client_request(metadata, "/api/v1/list")
        try:
            data: Dict[str, Any] = {}
            session: ConciergeSession = DirectConciergeSession(metadata=metadata)
            result_dict: Dict[str, Any] = session.list(data)

            # Return response to the HTTP client
            self.set_header("Content-Type", "application/json")
            self.write(result_dict)

        except Exception as exc:  # pylint: disable=broad-exception-caught
            self.process_exception(exc)
        finally:
            self.do_finish()
            self.application.finish_client_request(metadata, "/api/v1/list")
