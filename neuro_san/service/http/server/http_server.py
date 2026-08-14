
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
from typing import List

import asyncio
import json
import os
import random
from threading import Lock

import tornado
import tornado.netutil
import tornado.process

from leaf_common.asyncio.event_loop_lag_monitor import EventLoopLagMonitor
from leaf_common.config.config_util import ConfigUtil
from leaf_common.serialization.util.text_file_reader import TextFileReader
from leaf_common.utils.startable import Startable

from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.internals.interfaces.agent_state_listener import AgentStateListener
from neuro_san.internals.interfaces.agent_storage_source import AgentStorageSource
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.service.generic.agent_server_logging import AgentServerLogging
from neuro_san.service.generic.async_agent_service_provider import AsyncAgentServiceProvider
from neuro_san.service.http.config.http_server_config import ENV_HEALTH_PROBE_PORT
from neuro_san.service.http.config.http_server_config import HttpServerConfig
from neuro_san.service.http.handlers.concierge_handler import ConciergeHandler
from neuro_san.service.http.handlers.connectivity_handler import ConnectivityHandler
from neuro_san.service.http.handlers.debug_gc_handler import DebugGcHandler
from neuro_san.service.http.handlers.debug_tasks_handler import DebugTasksHandler
from neuro_san.service.http.handlers.function_handler import FunctionHandler
from neuro_san.service.http.handlers.health_check_handler import HealthCheckHandler
from neuro_san.service.http.handlers.openapi_publish_handler import OpenApiPublishHandler
from neuro_san.service.http.handlers.streaming_chat_handler import StreamingChatHandler
from neuro_san.service.http.handlers.profiler_control_handler import ProfilerControlHandler
from neuro_san.service.http.handlers.snapshot_handler import SnapshotHandler
from neuro_san.service.http.logging.http_logger import HttpLogger
from neuro_san.service.http.server.agent_authorization_policy import AgentAuthorizationPolicy
from neuro_san.service.http.server.health_probe_server import HealthProbeServer
from neuro_san.service.http.server.http_server_app import HttpServerApp
from neuro_san.service.http.server.resources_usage_logger import ResourcesUsageLogger
from neuro_san.service.interfaces.agent_authorizer import AgentAuthorizer
from neuro_san.service.interfaces.agent_server import AgentServer
from neuro_san.service.interfaces.event_loop_logger import EventLoopLogger
from neuro_san.service.mcp.handlers.mcp_root_handler import McpRootHandler
from neuro_san.service.utils.http_llm_tracer import HttpxLlmTracer
from neuro_san.service.utils.loop_timeline_tracer import LoopTimelineTracer
from neuro_san.service.utils.server_context import ServerContext
from neuro_san.service.utils.service_resources import ServiceResources
from neuro_san.service.utils.server_status import ServerStatus


DEFAULT_SERVER_NAME: str = 'neuro-san.Agent'
DEFAULT_SERVER_NAME_FOR_LOGS: str = 'Agent Server'
# By default, we allow unlimited concurrent requests, but this can be overridden by configuration.
DEFAULT_MAX_CONCURRENT_REQUESTS: int = 0

# Better that we kill ourselves than kubernetes doing it for us
# in the middle of a request if there are resource leaks.
# This is per the lifetime of the server (before it kills itself).
DEFAULT_REQUEST_LIMIT: int = 1000 * 1000


class HttpServer(AgentStateListener):
    """
    Class provides simple http endpoint for neuro-san API.
    """
    # pylint: disable=too-many-instance-attributes
    # pylint: disable=too-many-arguments, too-many-positional-arguments

    TIMEOUT_TO_START_SECONDS: int = 10

    def __init__(self,
                 server_context: ServerContext,
                 server_config: HttpServerConfig,
                 openapi_service_spec_path: str,
                 requests_limit: int,
                 concurrent_requests_limit: int,
                 logging_config: Dict[str, Any],
                 forwarded_request_metadata: str = AgentServer.DEFAULT_FORWARDED_REQUEST_METADATA):
        """
        Constructor:
        :param server_context: ServerContext with global-ish state
        :param server_config: http server run-time configuration
        :param openapi_service_spec_path: path to a file with OpenAPI service specification;
        :param requests_limit: The number of requests to service before shutting down.
                        This is useful to be sure production environments can handle
                        a service occasionally going down.
        :param concurrent_requests_limit: The number of concurrent requests to allow before rejecting new ones.
        :param logging_config: logging configuration
        :param forwarded_request_metadata: A space-delimited list of http metadata request keys
               to forward to logs/other requests
        """
        self.server_name_for_logs: str = "Http Server"
        self.server_config = server_config
        self.http_port = self.server_config.http_port
        self.server_context: ServerContext = server_context
        self.logging_config: Dict[str, Any] = logging_config

        # Randomize requests limit for this server instance.
        # Lower and upper bounds for number of requests before shutting down
        if requests_limit == -1:
            # Unlimited requests
            self.requests_limit = -1
        else:
            request_limit_lower = round(requests_limit * 0.90)
            request_limit_upper = round(requests_limit * 1.10)
            self.requests_limit = random.randint(request_limit_lower, request_limit_upper)
        self.concurrent_requests_limit = concurrent_requests_limit

        self.openapi_service_spec_path: str = openapi_service_spec_path
        self.forwarded_request_metadata: List[str] = forwarded_request_metadata.split(" ")
        self.logger = HttpLogger(self.forwarded_request_metadata, self.logging_config)
        self.allowed_agents: Dict[str, AsyncAgentServiceProvider] = {}
        self.authorization_policy: AgentAuthorizer = AgentAuthorizationPolicy(self.allowed_agents)
        self.lock = Lock()

        # Add listener to handle adding per-agent http service
        # (services map is defined by self.allowed_agents dictionary)
        network_storage_dict: Dict[str, AgentNetworkStorage] = self.server_context.get_network_storage_dict()
        for network_storage in network_storage_dict.values():
            network_storage.add_listener(self)

        self.server_context.set_agent_authorizer(self.authorization_policy)

    def start(self, startables: List[Startable]):
        """
        Method to be called by a thread running tornado HTTP server
        to actually start serving requests.
        :param startables: List of Startable instances to start once server
            has forked its multiple running instances.
        """
        # pylint: disable=too-many-statements
        app = self.make_app(self.requests_limit, self.concurrent_requests_limit, self.logger)

        self.logger.debug({}, "Serving agents: %s", repr(self.allowed_agents.keys()))

        # Create an HTTP server with run-time parameters
        server = tornado.httpserver.HTTPServer(
            app,
            idle_connection_timeout=self.server_config.http_idle_connection_timeout_seconds
        )

        if self.server_config.http_server_monitor_interval_seconds > 0:
            # Add resources usage logger to list of things we need to start
            # after http server is spun up:
            resources_logger: Startable =\
                ResourcesUsageLogger(
                    self.server_config.http_server_monitor_interval_seconds, self.http_port, self.logger)
            startables.append(resources_logger)

        # Add the isolated health-probe server. It binds a dedicated port
        # (default 8081, configurable via AGENT_HEALTH_PROBE_PORT; 0 disables)
        # and serves /, /healthz, /readyz, /livez on its own asyncio loop in
        # a dedicated thread -- so probes stay fast even when the main
        # Tornado loop is saturated by request work.
        probe_port: int = self.resolve_health_probe_port()
        if probe_port == self.http_port:
            self.logger.warning({},
                                "Health probe port %d is the same as main HTTP port; "
                                "dedicated probe server is not started, "
                                "but /healthz, /readyz, /livez remain registered on the main port", probe_port)
            probe_port = -1
        if probe_port > 0:
            startables.append(HealthProbeServer(
                port=probe_port,
                server_context=self.server_context,
                forwarded_request_metadata=self.forwarded_request_metadata,
                logging_config=self.logging_config,
            ))

        # Determine the number of worker processes to start.
        # If http_server_instances is 0, use the number of CPU cores.
        num_workers: int = self.server_config.http_server_instances
        if num_workers <= 0:
            num_workers = os.cpu_count() or 1

        # Bind the listening socket(s) BEFORE forking so every worker inherits
        # the same bound fd. Do NOT create/touch an IOLoop before fork_processes.
        sockets = tornado.netutil.bind_sockets(
            self.http_port, backlog=self.server_config.http_connections_backlog)

        # Do not create or access an asyncio/Tornado event loop before this call.
        worker_id: int = 0
        if num_workers > 1:
            worker_id = tornado.process.fork_processes(num_workers)

        # If num_workers == 1, we don't fork and worker_id of our single server process remains 0.
        self.logger.info({}, "Starting %d worker processes (worker_id=%d, pid=%d)",
                         num_workers, worker_id, os.getpid())
        # Register this worker's ID and total number of workers in the server context for use by other components.
        self.server_context.set_worker_info(worker_id, num_workers)

        # CRITICAL: attach the inherited sockets to THIS worker's IOLoop so it
        # actually accepts connections. server.start(N) did fork + add_sockets;
        # a bare fork_processes() does the fork but not the add_sockets.
        server.add_sockets(sockets)

        # Create all server context resources that need to be created after fork,
        # and start them if necessary.
        self.server_context.start()

        server_status: ServerStatus = self.server_context.get_server_status()
        server_status.http_service.set_status(True)
        self.logger.info({}, "HTTP server is running %d instances on port %d with backlog %d",
                         num_workers,
                         self.http_port,
                         self.server_config.http_connections_backlog)
        self.logger.info({}, "HTTP server idle connections timeout: %d seconds",
                         self.server_config.http_idle_connection_timeout_seconds)
        self.logger.info({}, "HTTP server is shutting down after %d requests", self.requests_limit)
        if self.concurrent_requests_limit > 0:
            self.logger.info({}, "HTTP server allows no more than %d concurrent requests",
                             self.concurrent_requests_limit)

        # If HTTP server is ready, our MCP server is also ready, if requested to run.
        if server_status.mcp_service.is_requested():
            server_status.mcp_service.set_status(True)
            mcp_version: str = self.server_context.get_mcp_server_context().get_protocol_version()
            self.logger.info({}, f"MCP server is running protocol {mcp_version}")

        if startables:
            for startable in startables:
                if isinstance(startable, Startable):
                    try:
                        startable.start()
                    except Exception as exception:  # pylint: disable=broad-exception-caught
                        self.logger.error(
                            {}, "Failed to start %s: %s",
                            startable.__class__.__name__, str(exception))

        main_loop = tornado.ioloop.IOLoop.current()

        # Enable event loop lag monitor if requested by environment variable.
        if ConfigUtil.get_bool(os.environ, "ENABLE_EVENT_LOOP_STATISTICS"):
            event_loop_monitor = \
                EventLoopLagMonitor(
                    sample_interval_seconds=1.0,
                    report_every_n_samples=30,
                    break_between_reports_seconds=30
                )
            ServiceResources.set_event_loop_monitor(event_loop_monitor)
            main_loop.spawn_callback(event_loop_monitor.run)

        # Optionally enable asyncio debug mode + slow-callback warnings on the
        # Tornado IOLoop's underlying asyncio loop. Off by default to avoid the
        # ~5-10% debug-mode overhead in production. Done after server.start()
        # forks so each worker enables it in its own loop.
        self._maybe_enable_asyncio_debug()

        # Optionally install the sys.setprofile-based loop timeline tracer.
        # Must be done on the Tornado loop thread, so we install it here --
        # this method runs on that thread and IOLoop.current().start() below
        # runs synchronously on the same thread.
        self._maybe_start_loop_timeline_tracer()

        # Optionally install the httpx-level LLM traffic tracer. Must run
        # BEFORE any LLM SDK constructs its httpx.AsyncClient, which happens
        # lazily on first LLM call, so installing here (before IOLoop.start)
        # is safely ahead of any traffic.
        self._maybe_install_http_llm_tracer()

        tornado.ioloop.IOLoop.current().start()
        self.logger.info({}, "Http server stopped.")

    def _maybe_enable_asyncio_debug(self) -> None:
        """
        Enable asyncio debug mode and the slow-callback warning on the
        current Tornado IOLoop's asyncio loop when requested via env vars.

        Controls:
          AGENT_ASYNCIO_DEBUG (bool, default false)
              When truthy, enables loop.set_debug(True). This turns on
              additional asyncio diagnostics including the slow-callback
              warning. Adds ~5-10% loop overhead -- leave off in production
              unless actively diagnosing.
          AGENT_ASYNCIO_SLOW_CALLBACK_DURATION_MS (int, default 100)
              Threshold in milliseconds. Any callback running longer than
              this on the Tornado loop will be logged at WARNING via the
              "asyncio" logger, with the source location of the offending
              callback.

        Must be called after server.start() (i.e. after fork) so each
        worker process configures its own loop.
        """
        if not ConfigUtil.get_bool(os.environ, "AGENT_ASYNCIO_DEBUG"):
            return

        raw_threshold: str = os.environ.get("AGENT_ASYNCIO_SLOW_CALLBACK_DURATION_MS", "100")
        try:
            threshold_ms: int = int(raw_threshold)
        except ValueError:
            self.logger.warning({},
                                "Invalid AGENT_ASYNCIO_SLOW_CALLBACK_DURATION_MS=%r; falling back to 100ms",
                                raw_threshold)
            threshold_ms = 100

        io_loop = tornado.ioloop.IOLoop.current()
        loop = getattr(io_loop, "asyncio_loop", None) or asyncio.get_event_loop()
        threshold_ms = max(threshold_ms, 1)
        loop.set_debug(True)
        loop.slow_callback_duration = threshold_ms / 1000.0
        self.logger.info(
            {},
            "asyncio debug enabled on Tornado loop; "
            "slow_callback_duration=%dms (warns via 'asyncio' logger)",
            threshold_ms,
        )

    # pylint: disable=attribute-defined-outside-init
    def _maybe_start_loop_timeline_tracer(self) -> None:
        """
        Start a LoopTimelineTracer on this thread if AGENT_LOOP_TIMELINE is
        truthy. The tracer records per-callback timing on the Tornado event
        loop -- a linear timeline of what ran and when.

        Environment variables:
          AGENT_LOOP_TIMELINE (bool, default false)
              Enables the tracer.
          AGENT_LOOP_TIMELINE_MAX_EVENTS (int, default 100000)
              Ring buffer size. Older events drop off as new ones arrive.
          AGENT_LOOP_TIMELINE_DUMP_PATH (str, default empty)
              If non-empty, register an atexit hook that writes the buffered
              timeline as JSONL to this path on graceful shutdown. When left
              empty the timeline stays in-memory only; snapshot it manually
              from a debug endpoint or signal handler.

        The tracer adds ~5-10% loop overhead; keep off in production unless
        actively diagnosing.
        """
        if not ConfigUtil.get_bool(os.environ, "AGENT_LOOP_TIMELINE"):
            return

        try:
            max_events: int = int(os.environ.get(
                "AGENT_LOOP_TIMELINE_MAX_EVENTS", str(LoopTimelineTracer.DEFAULT_MAX_EVENTS)))
        except ValueError:
            max_events = LoopTimelineTracer.DEFAULT_MAX_EVENTS
        if max_events <= 0:
            max_events = LoopTimelineTracer.DEFAULT_MAX_EVENTS

        self._loop_timeline_tracer = LoopTimelineTracer(max_events=max_events)

        dump_path: str = os.environ.get("AGENT_LOOP_TIMELINE_DUMP_PATH", "").strip()
        if dump_path:
            self._loop_timeline_tracer.register_atexit_dump(dump_path)
            self.logger.info(
                {}, "LoopTimelineTracer will dump to %s on shutdown", dump_path)

        # Start LAST so the tracer captures all callbacks executed after the loop starts running.
        self._loop_timeline_tracer.start()

    def _maybe_install_http_llm_tracer(self) -> None:
        """
        Install the httpx-level LLM traffic tracer if AGENT_HTTP_LLM_TRACE
        is truthy. Emits structured JSON events (http_llm_out /
        http_llm_in / http_llm_end / optional http_llm_chunk) to the
        dedicated logger "neuro_san.diagnostics.http_llm_trace" so
        post-run analysis can reconstruct the LLM traffic lifecycle of
        any user request via the user_req_id field.

        Environment variables:
          AGENT_HTTP_LLM_TRACE (bool, default false)
              Enables the tracer. Off by default.
          AGENT_HTTP_LLM_TRACE_INCLUDE_BODIES (bool, default false)
              When true, request and response bodies are logged verbatim
              (capped at 64 KB per body). Prompts + completions are large
              and sensitive; off by default.
          AGENT_HTTP_LLM_TRACE_CHUNKS (bool, default false)
              When true, emits one http_llm_chunk event per received
              body chunk. Massive log volume; enable only when
              investigating inter-chunk cadence.

        The tracer overhead is negligible (a few log writes per LLM
        call). Route the "neuro_san.diagnostics.http_llm_trace" logger
        to a separate file in logging.hocon for clean offline analysis.
        """
        if not ConfigUtil.get_bool(os.environ, "AGENT_HTTP_LLM_TRACE"):
            return

        include_bodies: bool = ConfigUtil.get_bool(
            os.environ, "AGENT_HTTP_LLM_TRACE_INCLUDE_BODIES")
        include_chunks: bool = ConfigUtil.get_bool(
            os.environ, "AGENT_HTTP_LLM_TRACE_CHUNKS")

        HttpxLlmTracer.install(
            include_bodies=include_bodies,
            include_chunks=include_chunks,
        )
        self.logger.info(
            {},
            "HttpxLlmTracer installed (include_bodies=%s include_chunks=%s)",
            include_bodies, include_chunks,
        )

    def resolve_health_probe_port(self) -> int:
        """
        Resolve the port for the isolated HealthProbeServer.

        Reads the AGENT_HEALTH_PROBE_PORT env var. Non-numeric values fall
        back to the default (8081), and a value of 0 (or negative) disables
        the separate probe server, in which case k8s / LB probes should hit
        the main port's registered health handlers.

        :return: A non-negative int. 0 disables the probe server.
        """
        raw: str = os.environ.get(ENV_HEALTH_PROBE_PORT, str(self.server_config.http_probe_port))
        try:
            value: int = int(raw)
        except ValueError:
            self.logger.warning({}, "Invalid %s=%r; falling back to default probe port %d",
                                ENV_HEALTH_PROBE_PORT, raw, self.server_config.http_probe_port)
            return self.server_config.http_probe_port
        return max(value, 0)

    def make_app(self, requests_limit: int, concurrent_requests_limit: int, logger: EventLoopLogger):
        """
        Construct tornado HTTP "application" to run.
        """
        # Do we need to enable HTTP request handlers?
        enable_http_handlers: bool = self.server_context.get_server_status().http_service.is_requested()

        request_initialize_data: Dict[str, Any] = self.build_request_data()
        # Resolve library versions once here; the same dict is passed to every
        # health handler on both the main port and the isolated probe server so
        # per-request probes never re-run importlib.metadata lookups.
        server_status = self.server_context.get_server_status()
        versions: Dict[str, Any] = server_status.get_versions()
        live_request_initialize_data: Dict[str, Any] = {
            "forwarded_request_metadata": self.forwarded_request_metadata,
            "server_status": server_status,
            "op": "live",
            "logging_config": self.logging_config,
            "versions": versions,
        }
        ready_request_initialize_data: Dict[str, Any] = {
            "forwarded_request_metadata": self.forwarded_request_metadata,
            "server_status": server_status,
            "op": "ready",
            "logging_config": self.logging_config,
            "versions": versions,
        }
        handlers = []
        # Health check handlers are enabled always
        handlers.append(("/", HealthCheckHandler, ready_request_initialize_data))
        handlers.append(("/healthz", HealthCheckHandler, ready_request_initialize_data))
        handlers.append(("/readyz", HealthCheckHandler, ready_request_initialize_data))
        handlers.append(("/livez", HealthCheckHandler, live_request_initialize_data))

        # Setup handler for profiler control
        handlers.append(("/profiler", ProfilerControlHandler))

        # Setup handler for system snapshot query:
        handlers.append(("/resources_utilization", SnapshotHandler, {"http_port": self.http_port}))

        # Setup handler for on-demand asyncio-task dump across used AsyncioExecutors.
        # Gated behind ENABLE_RUN_TIME_STATISTICS (same as /profiler and /resources_utilization).
        handlers.append(("/debug/tasks", DebugTasksHandler, {"server_context": self.server_context}))

        # Setup handler for on-demand full Python garbage collection.
        # Reports collected object count + before/after process memory.
        # Same env-var gate as the other /debug endpoints.
        handlers.append(("/debug/gc", DebugGcHandler))

        if enable_http_handlers:
            handlers.append(("/api/v1/list", ConciergeHandler, request_initialize_data))
            handlers.append(("/api/v1/docs", OpenApiPublishHandler, request_initialize_data))

            # Register templated request paths for agent API methods:
            # regexp format used here is that of Python Re standard library.
            handlers.append((r"/api/v1/(.+)/function", FunctionHandler, request_initialize_data))
            handlers.append((r"/api/v1/(.+)/connectivity", ConnectivityHandler, request_initialize_data))
            handlers.append((r"/api/v1/(.+)/streaming_chat", StreamingChatHandler, request_initialize_data))

        # Register MCP "root" handler for all MCP requests
        # if MCP server is enabled:
        if self.server_context.get_mcp_server_context().is_enabled():
            handlers.append((r"/mcp", McpRootHandler, request_initialize_data))

        return HttpServerApp(
            handlers,
            requests_limit,
            concurrent_requests_limit,
            logger,
            self.forwarded_request_metadata)

    def agent_added(self, agent_name: str, source: AgentStorageSource):
        """
        Add agent to the map of known agents
        :param agent_name: name of an agent
        :param source: The AgentStorageSource source of the message
        """
        agent_network_provider: AgentNetworkProvider = source.get_agent_network_provider(agent_name)
        # There are some timing scenarios where at this point agent network provider might not be available,
        # even though we got a notification that agent is added.
        # One example: temporary agent network expiration.
        # In this case, log the message and finish processing.
        if agent_network_provider is None:
            self.logger.info({}, "Agent %s has already expired - adding to service cancelled.",
                             agent_name)
            return

        # Convert back to a single string as required by constructor
        request_metadata_str: str = " ".join(self.forwarded_request_metadata)
        agent_server_logging: AgentServerLogging = \
            AgentServerLogging(self.server_name_for_logs, request_metadata_str, self.logging_config)
        agent_service_provider: AsyncAgentServiceProvider = \
            AsyncAgentServiceProvider(
                self.logger,
                None,
                agent_name,
                agent_network_provider,
                agent_server_logging,
                self.server_context)
        self.allowed_agents[agent_name] = agent_service_provider
        self.logger.info({}, "Added agent %s to allowed http service list", agent_name)

    def agent_removed(self, agent_name: str, source: AgentStorageSource):
        """
        Remove agent from the map of known agents
        :param agent_name: name of an agent
        :param source: The AgentStorageSource source of the message
        """
        self.allowed_agents.pop(agent_name, None)
        self.logger.info({}, "Removed agent %s from allowed http service list", agent_name)

    def agent_modified(self, agent_name: str, source: AgentStorageSource):
        """
        Agent is being modified in the service scope.
        :param agent_name: name of an agent
        :param source: The AgentStorageSource source of the message
        """
        agent_service_provider: AsyncAgentServiceProvider = self.allowed_agents.get(agent_name, None)
        if agent_service_provider is not None:
            agent_service_provider.reset_service()
            self.logger.info({}, "Reset service for modified agent %s", agent_name)

    def build_request_data(self) -> Dict[str, Any]:
        """
        Build request data for Http handlers.
        :return: a dictionary with request data to be passed to an http handler.
        """
        open_api_dict: Dict[str, Any] = None
        try:
            f_str: str = TextFileReader.read_text_file(self.openapi_service_spec_path)
            open_api_dict = json.loads(f_str)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(f"Failed to load '{self.openapi_service_spec_path}'") from exc

        return {
            "agent_policy": self.authorization_policy,  # now redundant cuz server_context has it
            "forwarded_request_metadata": self.forwarded_request_metadata,
            "openapi_service_spec": open_api_dict,
            "server_context": self.server_context,
            "logging_config": self.logging_config,
            "keep_alive_interval_seconds": self.server_config.stream_keep_alive_with_progress_interval_seconds,
        }
