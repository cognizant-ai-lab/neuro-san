
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
Base request handler with HoneyHive tracing support.
"""
from typing import Any
from typing import Dict
from typing import Optional

from neuro_san.service.http.handlers.base_request_handler import BaseRequestHandler
from neuro_san.internals.run_context.tracing.honeyhive_tracing import TracingContext
from neuro_san.internals.run_context.tracing.honeyhive_tracing import enrich_session
from neuro_san.internals.run_context.tracing.honeyhive_tracing import is_honeyhive_enabled


class TracingRequestHandler(BaseRequestHandler):
    """
    Extended base request handler that adds HoneyHive tracing support.

    This handler automatically creates a HoneyHive session for each request
    when HoneyHive is configured and enabled.
    """

    def __init__(self, *args, **kwargs):
        """
        Initialize the handler with tracing support.
        """
        super().__init__(*args, **kwargs)
        self.tracing_context: Optional[TracingContext] = None

    def start_tracing(self, agent_name: str, endpoint: str) -> Optional[TracingContext]:
        """
        Start a HoneyHive tracing session for this request.

        :param agent_name: Name of the agent being called
        :param endpoint: The API endpoint being called
        :return: TracingContext if tracing is enabled, None otherwise
        """
        if not is_honeyhive_enabled():
            return None

        metadata = self.get_metadata()
        request_id = metadata.get("request_id", f"request-{self.request_id}")

        session_name = f"{agent_name}/{endpoint}"
        session_metadata = {
            "agent_name": agent_name,
            "endpoint": endpoint,
            "request_id": request_id,
            "http_method": self.request.method,
            "uri": self.request.uri,
        }

        self.tracing_context = TracingContext(
            session_name=session_name,
            metadata=session_metadata
        )
        self.tracing_context.start_session()

        return self.tracing_context

    def stop_tracing(self, error: Optional[str] = None) -> None:
        """
        Stop the HoneyHive tracing session for this request.

        :param error: Optional error message if the request failed
        """
        if self.tracing_context is not None:
            self.tracing_context.stop_session(error)
            self.tracing_context = None

    def enrich_request_tracing(
        self,
        metadata: Optional[Dict[str, Any]] = None,
        metrics: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Add additional metadata or metrics to the current tracing session.

        :param metadata: Additional metadata to add
        :param metrics: Metrics to add
        """
        if self.tracing_context is not None:
            if metadata:
                enrich_session(metadata=metadata)
            if metrics:
                enrich_session(metrics=metrics)
