
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

import json

from neuro_san.service.http.handlers.base_request_handler import BaseRequestHandler


class OpenApiPublishHandler(BaseRequestHandler):
    """
    Handler class for neuro-san OpenAPI service spec publishing"concierge" API call.
    """

    def get(self):
        """
        Implementation of GET request handler
        for "publish my OpenAPI specification document" call.
        """
        metadata: Dict[str, Any] = self.get_metadata()
        self.application.start_client_request(metadata, "/api/v1/docs")
        try:
            with open(self.openapi_service_spec_path, "r", encoding='utf-8') as f_out:
                result_dict: Dict[str, Any] = json.load(f_out)
            # Return json data to the HTTP client
            self.set_header("Content-Type", "application/json")
            self.write(result_dict)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self.process_exception(exc)
        finally:
            self.do_finish()
            self.application.finish_client_request(metadata, "/api/v1/docs")
