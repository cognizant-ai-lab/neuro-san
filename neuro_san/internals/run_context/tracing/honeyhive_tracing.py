
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
HoneyHive tracing integration for neuro-san.

This module provides utilities for integrating HoneyHive tracing into neuro-san.
HoneyHive is an optional dependency - if not installed, tracing will be disabled.

Environment variables:
    HH_API_KEY: HoneyHive API key (required for tracing)
    HH_PROJECT: HoneyHive project name (required for tracing)
    HH_SOURCE: Source identifier (default: "neuro-san")
    HH_ENABLED: Set to "false" to disable tracing even if API key is present
"""
from typing import Any
from typing import Callable
from typing import Dict
from typing import Optional
from typing import TypeVar

import functools
import os
from logging import Logger
from logging import getLogger

# Type variable for generic function signatures
F = TypeVar('F', bound=Callable[..., Any])

# Module-level state
_honeyhive_available: bool = False
_logger: Logger = getLogger(__name__)

# Try to import HoneyHive
try:
    from honeyhive import HoneyHiveTracer
    from honeyhive import trace as hh_trace
    from honeyhive import atrace as hh_atrace
    from honeyhive import enrich_span as hh_enrich_span
    from honeyhive import enrich_session as hh_enrich_session
    _honeyhive_available = True
except ImportError:
    HoneyHiveTracer = None
    hh_trace = None
    hh_atrace = None
    hh_enrich_span = None
    hh_enrich_session = None


def is_honeyhive_available() -> bool:
    """
    Check if HoneyHive SDK is installed.

    :return: True if HoneyHive SDK is available
    """
    return _honeyhive_available


def is_honeyhive_enabled() -> bool:
    """
    Check if HoneyHive tracing is enabled.

    Tracing is enabled if:
    - HoneyHive SDK is installed
    - HH_API_KEY environment variable is set
    - HH_PROJECT environment variable is set
    - HH_ENABLED is not set to "false"

    :return: True if HoneyHive tracing is enabled
    """
    if not _honeyhive_available:
        return False

    if os.environ.get("HH_ENABLED", "true").lower() == "false":
        return False

    api_key = os.environ.get("HH_API_KEY")
    project = os.environ.get("HH_PROJECT")

    return bool(api_key and project)


def init_session(
    session_name: str,
    metadata: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None
) -> Optional[Any]:
    """
    Initialize a HoneyHive tracing session.

    :param session_name: Name for this session (e.g., agent name or request ID)
    :param metadata: Optional metadata to attach to the session
    :param session_id: Optional session ID for distributed tracing
    :return: HoneyHiveTracer instance if enabled, None otherwise
    """
    if not is_honeyhive_enabled():
        return None

    try:
        api_key = os.environ.get("HH_API_KEY")
        project = os.environ.get("HH_PROJECT")
        source = os.environ.get("HH_SOURCE", "neuro-san")
        server_url = os.environ.get("HH_API_URL")

        init_kwargs = {
            "api_key": api_key,
            "project": project,
            "session_name": session_name,
            "source": source,
        }

        if server_url:
            init_kwargs["server_url"] = server_url

        if session_id:
            init_kwargs["session_id"] = session_id

        tracer = HoneyHiveTracer.init(**init_kwargs)

        if metadata and tracer:
            enrich_session(metadata=metadata)

        return tracer

    except Exception as exc:
        _logger.warning("Failed to initialize HoneyHive session: %s", str(exc))
        return None


def flush_session() -> None:
    """
    Flush any pending trace data to HoneyHive.

    Should be called at the end of a request to ensure all data is sent.
    """
    if not is_honeyhive_enabled():
        return

    try:
        HoneyHiveTracer.flush()
    except Exception as exc:
        _logger.warning("Failed to flush HoneyHive session: %s", str(exc))


def enrich_session(
    metadata: Optional[Dict[str, Any]] = None,
    metrics: Optional[Dict[str, Any]] = None,
    feedback: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None
) -> None:
    """
    Enrich the current HoneyHive session with additional data.

    :param metadata: Metadata to add to the session
    :param metrics: Metrics to add to the session
    :param feedback: Feedback to add to the session
    :param session_id: Optional specific session ID to enrich
    """
    if not is_honeyhive_enabled():
        return

    try:
        kwargs = {}
        if metadata:
            kwargs["metadata"] = metadata
        if metrics:
            kwargs["metrics"] = metrics
        if feedback:
            kwargs["feedback"] = feedback
        if session_id:
            kwargs["session_id"] = session_id

        if kwargs:
            hh_enrich_session(**kwargs)

    except Exception as exc:
        _logger.warning("Failed to enrich HoneyHive session: %s", str(exc))


def enrich_span(
    metadata: Optional[Dict[str, Any]] = None,
    metrics: Optional[Dict[str, Any]] = None,
    inputs: Optional[Dict[str, Any]] = None,
    outputs: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None
) -> None:
    """
    Enrich the current span with additional data.

    Must be called from within a traced function.

    :param metadata: Metadata to add to the span
    :param metrics: Metrics to add to the span
    :param inputs: Inputs to add to the span
    :param outputs: Outputs to add to the span
    :param error: Error message if an error occurred
    """
    if not is_honeyhive_enabled():
        return

    try:
        kwargs = {}
        if metadata:
            kwargs["metadata"] = metadata
        if metrics:
            kwargs["metrics"] = metrics
        if inputs:
            kwargs["inputs"] = inputs
        if outputs:
            kwargs["outputs"] = outputs
        if error:
            kwargs["error"] = error

        if kwargs:
            hh_enrich_span(**kwargs)

    except Exception as exc:
        _logger.warning("Failed to enrich HoneyHive span: %s", str(exc))


def trace(
    event_type: str = "chain",
    metadata: Optional[Dict[str, Any]] = None
) -> Callable[[F], F]:
    """
    Decorator to trace a synchronous function with HoneyHive.

    If HoneyHive is not enabled, returns the function unchanged.

    :param event_type: Type of event (chain, tool, model)
    :param metadata: Optional metadata to attach to the span
    :return: Decorated function
    """
    def decorator(func: F) -> F:
        if not is_honeyhive_enabled():
            return func

        decorator_kwargs = {
            "event_type": event_type,
        }
        if metadata:
            decorator_kwargs["metadata"] = metadata

        return hh_trace(**decorator_kwargs)(func)

    return decorator


def atrace(
    event_type: str = "chain",
    metadata: Optional[Dict[str, Any]] = None
) -> Callable[[F], F]:
    """
    Decorator to trace an async function with HoneyHive.

    If HoneyHive is not enabled, returns the function unchanged.

    :param event_type: Type of event (chain, tool, model)
    :param metadata: Optional metadata to attach to the span
    :return: Decorated function
    """
    def decorator(func: F) -> F:
        if not is_honeyhive_enabled():
            return func

        decorator_kwargs = {
            "event_type": event_type,
        }
        if metadata:
            decorator_kwargs["metadata"] = metadata

        return hh_atrace(**decorator_kwargs)(func)

    return decorator


def traced_function(
    name: Optional[str] = None,
    event_type: str = "chain",
    metadata: Optional[Dict[str, Any]] = None
) -> Callable[[F], F]:
    """
    Decorator to trace a function with HoneyHive, with custom name support.

    Automatically detects if the function is async and uses the appropriate tracer.

    :param name: Custom name for the span (defaults to function name)
    :param event_type: Type of event (chain, tool, model)
    :param metadata: Optional metadata to attach to the span
    :return: Decorated function
    """
    # Import asyncio at module level would cause issues if honeyhive is not installed
    import asyncio  # pylint: disable=import-outside-toplevel

    def decorator(func: F) -> F:
        if not is_honeyhive_enabled():
            return func

        span_metadata = metadata.copy() if metadata else {}
        if name:
            span_metadata["span_name"] = name

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                return await func(*args, **kwargs)

            decorator_kwargs = {"event_type": event_type}
            if span_metadata:
                decorator_kwargs["metadata"] = span_metadata

            return hh_atrace(**decorator_kwargs)(async_wrapper)

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        decorator_kwargs = {"event_type": event_type}
        if span_metadata:
            decorator_kwargs["metadata"] = span_metadata

        return hh_trace(**decorator_kwargs)(sync_wrapper)

    return decorator


class TracingContext:
    """
    Context manager for HoneyHive tracing sessions.

    Usage:
        with TracingContext("my_session", metadata={"key": "value"}) as ctx:
            # Your code here
            ctx.enrich_session(metrics={"latency": 100})
    """

    def __init__(
        self,
        session_name: str,
        metadata: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None
    ):
        """
        Initialize the tracing context.

        :param session_name: Name for this session
        :param metadata: Optional metadata to attach to the session
        :param session_id: Optional session ID for distributed tracing
        """
        self.session_name = session_name
        self.metadata = metadata
        self.session_id = session_id
        self.tracer = None

    def start_session(self) -> "TracingContext":
        """Start the tracing session."""
        self.tracer = init_session(
            session_name=self.session_name,
            metadata=self.metadata,
            session_id=self.session_id
        )
        return self

    def stop_session(self, error: Optional[str] = None) -> None:
        """Stop the tracing session and flush data."""
        if error is not None:
            enrich_session(metadata={"error": error})
        flush_session()

    def __enter__(self) -> "TracingContext":
        """Enter the context and initialize the session."""
        return self.start_session()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit the context and flush the session."""
        error = str(exc_val) if exc_type is not None else None
        self.stop_session(error)

    async def __aenter__(self) -> "TracingContext":
        """Async enter the context and initialize the session."""
        return self.start_session()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async exit the context and flush the session."""
        error = str(exc_val) if exc_type is not None else None
        self.stop_session(error)

    def get_session_id(self) -> Optional[str]:
        """
        Get the session ID for distributed tracing.

        :return: Session ID if available
        """
        if self.tracer:
            return self.tracer.session_id
        return self.session_id

    def enrich_session_data(self, **kwargs) -> None:
        """Enrich the current session with additional data."""
        enrich_session(**kwargs)

    def enrich_span_data(self, **kwargs) -> None:
        """Enrich the current span with additional data."""
        enrich_span(**kwargs)
