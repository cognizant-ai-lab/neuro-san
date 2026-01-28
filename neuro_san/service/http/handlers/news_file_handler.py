
# Copyright (C) 2023-2026 Cognizant Technology Solutions Corp, www.cognizant.com.
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
Handler for writing news content to a predefined local file.

This handler is part of a demo hack to allow external systems (like the repsim UI)
to inject news content that can be read by coded tools running in the neuro-san server.
"""
from typing import Any
from typing import Dict
from typing import List

from http import HTTPStatus

import json
import os

from tornado.web import RequestHandler
from neuro_san.service.http.logging.http_logger import HttpLogger


# Default file path for news content. Can be overridden via environment variable.
DEFAULT_NEWS_FILE_PATH: str = "/tmp/repsim_news.txt"


class NewsFileHandler(RequestHandler):
    """
    Handler class for writing news content to a local file.

    This endpoint accepts POST requests with JSON body containing a "text" field,
    and writes that text to a predefined local file location.
    """

    # pylint: disable=attribute-defined-outside-init
    # pylint: disable=unused-argument
    def initialize(self, forwarded_request_metadata: List[str], **kwargs):
        """
        This method is called by Tornado framework to allow
        injecting service-specific data into local handler context.
        :param forwarded_request_metadata: list of client metadata keys
        :param kwargs: additional keyword arguments (ignored)
        """
        self.logger = HttpLogger(forwarded_request_metadata)
        self.news_file_path: str = os.environ.get(
            "REPSIM_NEWS_FILE_PATH", DEFAULT_NEWS_FILE_PATH
        )

        if os.environ.get("AGENT_ALLOW_CORS_HEADERS") is not None:
            self.set_header("Access-Control-Allow-Origin", "*")
            self.set_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.set_header("Access-Control-Allow-Headers", "Content-Type, Transfer-Encoding")

    async def post(self):
        """
        Handle POST request to write news content to the file.

        Expected JSON body:
        {
            "text": "The news content to write"
        }

        Returns:
        - 200 OK with {"status": "ok"} on success
        - 400 Bad Request if JSON is invalid or "text" field is missing
        - 500 Internal Server Error on file write failure
        """
        try:
            body: Dict[str, Any] = json.loads(self.request.body)
            text: str = body.get("text")

            if text is None:
                self.set_status(HTTPStatus.BAD_REQUEST)
                self.write({"error": "Missing 'text' field in request body"})
                self.finish()
                return

            with open(self.news_file_path, "w", encoding="utf-8") as news_file:
                news_file.write(text)

            self.logger.info({}, "News content written to %s", self.news_file_path)
            self.set_header("Content-Type", "application/json")
            self.write({"status": "ok"})

        except json.JSONDecodeError:
            self.set_status(HTTPStatus.BAD_REQUEST)
            self.write({"error": "Invalid JSON format"})
            self.logger.error({}, "Invalid JSON format in news file request")

        except OSError as exc:
            self.set_status(HTTPStatus.INTERNAL_SERVER_ERROR)
            self.write({"error": f"Failed to write news file: {str(exc)}"})
            self.logger.error({}, "Failed to write news file: %s", str(exc))

        except Exception as exc:  # pylint: disable=broad-exception-caught
            self.set_status(HTTPStatus.INTERNAL_SERVER_ERROR)
            self.write({"error": "Internal server error"})
            self.logger.error({}, "Unexpected error in news file handler: %s", str(exc))

        finally:
            self.finish()

    async def get(self):
        """
        Handle GET request to read current news content from the file.

        Returns:
        - 200 OK with {"text": "content"} if file exists
        - 200 OK with {"text": ""} if file does not exist
        - 500 Internal Server Error on file read failure
        """
        try:
            if os.path.exists(self.news_file_path):
                with open(self.news_file_path, "r", encoding="utf-8") as news_file:
                    content: str = news_file.read()
            else:
                content = ""

            self.set_header("Content-Type", "application/json")
            self.write({"text": content})

        except OSError as exc:
            self.set_status(HTTPStatus.INTERNAL_SERVER_ERROR)
            self.write({"error": f"Failed to read news file: {str(exc)}"})
            self.logger.error({}, "Failed to read news file: %s", str(exc))

        except Exception as exc:  # pylint: disable=broad-exception-caught
            self.set_status(HTTPStatus.INTERNAL_SERVER_ERROR)
            self.write({"error": "Internal server error"})
            self.logger.error({}, "Unexpected error in news file handler: %s", str(exc))

        finally:
            self.finish()

    async def delete(self):
        """
        Handle DELETE request to clear the news file.

        Returns:
        - 200 OK with {"status": "ok"} on success
        - 200 OK with {"status": "ok"} if file does not exist (idempotent)
        - 500 Internal Server Error on file delete failure
        """
        try:
            if os.path.exists(self.news_file_path):
                os.remove(self.news_file_path)
                self.logger.info({}, "News file deleted: %s", self.news_file_path)

            self.set_header("Content-Type", "application/json")
            self.write({"status": "ok"})

        except OSError as exc:
            self.set_status(HTTPStatus.INTERNAL_SERVER_ERROR)
            self.write({"error": f"Failed to delete news file: {str(exc)}"})
            self.logger.error({}, "Failed to delete news file: %s", str(exc))

        except Exception as exc:  # pylint: disable=broad-exception-caught
            self.set_status(HTTPStatus.INTERNAL_SERVER_ERROR)
            self.write({"error": "Internal server error"})
            self.logger.error({}, "Unexpected error in news file handler: %s", str(exc))

        finally:
            self.finish()

    def get_metadata(self) -> Dict[str, Any]:
        """
        Get request metadata
        """
        return {}

    def data_received(self, chunk):
        """
        Method overrides abstract method of RequestHandler
        with no-op implementation.
        """
        return

    async def options(self, *_args, **_kwargs):
        """
        Handles OPTIONS requests for CORS support
        """
        self.set_status(HTTPStatus.NO_CONTENT)
        self.finish()
