
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

# This Dockerfile is expected to be run from the top-level of neuro-san.

# If you find yourself wanting to modify this file
# and check it into the neuro-san repo or modify it in place with the
# neuro-san source code, chances are you shouldn't. Instead, strongly
# consider creating your own repo with your own agents and using this
# Dockerfile and accompanying scripts as a basis to riff on for your
# own projects.  Your own requirements.txt file for your project will
# need to include neuro-san as a dependency.
#
# Use ./neuro_san/deploy/build.sh to build this container from within the
# neuro-san repo. After a successful build of the container, you can use
# ./neuro_san/deploy/run.sh to run the built container locally.
#
# To find server-oriented environment variables to help you configure things
# how you want, search for "ENV AGENT_" in this file.

# Build arguments
ARG NEURO_SAN_VERSION="Unspecified"
ARG PACKAGE_INSTALL="/usr/local/lib/python3.12/site-packages"

# Stage 1: Builder Stage - Use our python base image for installations
# Set python image as base image
FROM python:3.12-slim as builder

# Set the shell and options per hadolint recommendations
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Reset to the root directory
WORKDIR /

# App-specific constants
ENV USERNAME="neuro-san"
ENV APP_HOME="/usr/local/${USERNAME}"
ENV APP_SOURCE="${APP_HOME}/myapp"
ENV PIP3_VERSION="25.0.1"

# Explicitly get the desired pip version
RUN pip3 install --upgrade pip==${PIP3_VERSION} --no-cache-dir ; mkdir -p ${APP_SOURCE}

# [s] allows for the requirements file not to be there.
COPY ./requirement[s].txt ${APP_SOURCE}
RUN pip install --prefix=/install --no-cache-dir -r ${APP_SOURCE}/requirements.txt

# Stage 2: Final Stage - Use a slim Python image
FROM python:3.12-slim AS final

# Set the shell and options in each FROM section per hadolint recommendations
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Set up user for app running in container
ENV USERNAME="neuro-san"
ENV APP_HOME="/usr/local/${USERNAME}"
ENV APP_SOURCE="${APP_HOME}/myapp"

RUN \
    useradd -ms /bin/bash -d ${APP_HOME} -u 1001 ${USERNAME} \
    && echo ${USERNAME}:pw | chpasswd \
    && mkdir -p ${APP_HOME}/.ssh \
    && chown -R ${USERNAME}: ${APP_HOME} \
    && chown -R ${USERNAME}: /usr/local/ \
    && chown -R ${USERNAME}: /var/log \
    && mkdir -p ${APP_SOURCE}

# This is the port the service will accept http requests on.
# This should be consistent with the main port for the service as described
# in any kubernetes <service>.yaml file
# This port number is also mentioned as AGENT_HTTP_PORT below
# and ServiceAgentSession.DEFAULT_HTTP_PORT
EXPOSE 8080

# Copy installed dependencies from the builder stage
COPY --from=builder /install /usr/local

# Copy application code and necessary files
# Note: The registries directory where agent definitions live is mandatory
#       The coded_tools directory where agent code lives is optional
#       [s] allows for registries/coded_tools from within client repo or neuro-san repo
COPY ./neuro_san/registrie[s] ./registrie[s] ${APP_SOURCE}/registries/
COPY ./neuro_san/coded_tool[s] ./coded_tool[s] ${APP_SOURCE}/coded_tools/

# Copy application code and necessary files if we are running within the neuro-san repo
# [n] allows this to not have to be there for client repo builds.
COPY ./neuro_sa[n] ${APP_SOURCE}/neuro_san
RUN chmod -R a+r ${APP_SOURCE}

# Set up the entry point for when the container is run
USER ${USERNAME}
WORKDIR ${APP_SOURCE}

# RUN echo "$(pip show neuro-san | grep Location | awk '{print $2}')"
# This value below comes from the above RUN command.
# Cannot set ENV vars in Dockerfiles based on shell output within in-progress container build,
# only from build args.
ARG PACKAGE_INSTALL
ENV PACKAGE_INSTALL="${PACKAGE_INSTALL}"
ENV PACKAGE_DEPLOY="${PACKAGE_INSTALL}/neuro_san/deploy"
ENV APP_ENTRYPOINT="${PACKAGE_DEPLOY}/entrypoint.sh"

ARG NEURO_SAN_VERSION


#
# API Keys for LLM Access
#
# Which env vars you need may vary depending on which LLM(s) you choose for your own setup.
# See https://github.com/cognizant-ai-lab/neuro-san/blob/main/docs/agent_hocon_reference.md#llm_config
# for details on different LLM providers' needs for out-of-the-box support.
#
# Note that you really really don't want to leak secrets by checking the actual values into source control.
# These are best injected into the container via environment variables at runtime ala:
#   docker run -e OPENAI_API_KEY=...
#

# OpenAI/ChatGPT access
ENV OPENAI_API_KEY=""

# Amazon Bedrock access
ENV AWS_ACCESS_KEY_ID=""
ENV AWS_SECRET_ACCESS_KEY=""

# Anthropic/Claude access
ENV ANTHROPIC_API_KEY=""

# MicroSoft Azure/OpenAI access
# OPENAI_API_KEY is a fallback for AZURE_OPENAI_API_KEY
# ENV AZURE_OPENAI_API_KEY=""
ENV AZURE_OPENAI_ENDPOINT=""

# Google/Gemini access
ENV GOOGLE_API_KEY=""

# NVidia LLM access
ENV NVIDIA_API_KEY=""

#
# Server configuration
#

# Where to find the tool registry manifest file which lists all the agent hocon
# files to serve up from this server instance.  To specify multiple manifest files,
# simply use a delimited list of manifest files approriate to the OS
# (delimiter is ':' on linux, ';' on Windows).  Manifest dictionaries will then effectively
# be merged, where content coming from manifests later in the list have precedence.
ENV AGENT_MANIFEST_FILE="${APP_SOURCE}/registries/manifest.hocon"

# An llm_info hocon file with user-provided llm descriptions that are to be used
# in addition to the neuro-san defaults.
ENV AGENT_LLM_INFO_FILE=""

# A toolbox_info hocon file with user-provided base tool and coded tool
# descriptions that are to be used in addition to the neuro-san defaults.
ENV AGENT_TOOLBOX_INFO_FILE=""

# Where to find the classes for CodedTool class implementations
# that are used by specific agent networks.
ENV AGENT_TOOL_PATH="${APP_SOURCE}/coded_tools"

# Where to find the configuration file for Python logging.
# See https://docs.python.org/3/library/logging.config.html#dictionary-schema-details
# as to how this file can be configured for your own needs.  Examples there are provided in YAML,
# but these can be easily translated to JSON or HOCON (which we prefer).
# Another good resource: https://docs.python.org/3/howto/logging-cookbook.html
ENV AGENT_SERVICE_LOG_JSON="${PACKAGE_DEPLOY}/logging.hocon"

# Threshold for logging.
# See https://docs.python.org/3/library/logging.html#logging.Handler.setLevel
# and https://docs.python.org/3/library/logging.html#logging-levels for details.
ENV AGENT_SERVICE_LOG_LEVEL="DEBUG"

# Optional input slice specification for user input in request logging
# By default this is empty, which means all user input is logged.
# This can be an integer where:
#   > 0 means first N characters of user input is logged
#   0 means no user input is logged
#   < 0 means last N characters of user input is logged
ENV AGENT_REQUEST_LOGGING_INPUT_SLICE=""

# The name of the service for health reporting purposes
ENV AGENT_SERVER_NAME="neuro-san.Agent"

# Name of the service as seen in logs
ENV AGENT_SERVER_NAME_FOR_LOGS="Agent Server"

# A space-delimited list of http metadata request keys to forward to logs/other requests
# You can see how these are used in the AGENT_SERVICE_LOG_JSON file (see above) and
# customize this and the AGENT_SERVER_LOG_JSON file to your needs.
# Note that any metadata key needs to be all lowercase.
ENV AGENT_FORWARDED_REQUEST_METADATA="request_id user_id"

# Port number for http service endpoint
# If you are changing this, you should also change the EXPOSE port above
# and when running your container locally be sure to have a -p <port>:<port> entry
# for it on your docker run command line.
ENV AGENT_HTTP_PORT="8080"

# Dedicated port for the isolated health-probe server. Serves /, /healthz,
# /readyz, /livez on its own asyncio event loop in a dedicated thread, so
# probes stay fast even when the main Tornado loop is saturated by request
# work. Uses SO_REUSEPORT so every worker process binds the same port and
# the kernel distributes accepted connections across them.
#
# Set to 0 to disable the isolated probe server (in that case probes must
# hit AGENT_HTTP_PORT, which continues to register the same handlers for
# backward compatibility).
#
# Point your Kubernetes livenessProbe.httpGet.port at this port for
# best-case probe responsiveness under load.
ENV AGENT_HEALTH_PROBE_PORT="8081"

# Enable asyncio debug mode on the Tornado main event loop in each worker.
# When set to "true"/"1"/"yes", the server calls loop.set_debug(True), which:
#   - turns on additional asyncio diagnostics
#   - logs a WARNING via the "asyncio" logger whenever any callback runs longer
#     than AGENT_ASYNCIO_SLOW_CALLBACK_DURATION_MS (see below). The warning
#     includes the source location of the offending callback -- the diagnostic
#     to use when /livez probe latency spikes under load.
# Adds ~5-10% loop overhead. Leave off in production unless diagnosing.
ENV AGENT_ASYNCIO_DEBUG="false"

# Slow-callback threshold in milliseconds. Only consulted when
# AGENT_ASYNCIO_DEBUG is enabled. Lower values surface smaller hogs but
# create more log volume. 50-100ms is a good first pass.
ENV AGENT_ASYNCIO_SLOW_CALLBACK_DURATION_MS="100"

# Enable the sys.setprofile-based loop timeline tracer on the Tornado
# main event loop. When enabled, records a linear timeline of every
# scheduled unit of work run by the loop -- task steps, done callbacks,
# call_soon callbacks, timer callbacks -- keyed by task name or callback
# qualname. Useful for answering "what is occupying the loop right now?"
# Adds ~5-10% loop overhead. Leave OFF in production unless diagnosing.
ENV AGENT_LOOP_TIMELINE="false"

# Ring buffer size for the loop timeline tracer. Older events drop off as
# newer ones arrive. Only consulted when AGENT_LOOP_TIMELINE is enabled.
ENV AGENT_LOOP_TIMELINE_MAX_EVENTS="100000"

# If non-empty AND AGENT_LOOP_TIMELINE is enabled, the tracer writes its
# buffered events to this JSONL file on graceful process shutdown. Leave
# empty to keep the timeline in-memory only (snapshot via a debug endpoint
# or signal handler at runtime).
ENV AGENT_LOOP_TIMELINE_DUMP_PATH=""

# Maximm number of requests that can be served at the same time
# A value of 0 indicates unlimited requests are handled.
ENV AGENT_MAX_CONCURRENT_REQUESTS="50"

# Maximum number of worker threads per request.
# Default of <= 0 (or unset) indicates system default of (num_cpus + 4).
ENV AGENT_MAX_WORKERS_PER_REQUEST="0"

# Number of requests served before the server shuts down in an orderly fashion.
# This is useful for testing response handling in clusters with duplicated pods.
# A value of -1 indicates unlimited requests are handled.
ENV AGENT_REQUEST_LIMIT="-1"

# If this value is specified and >0,
# it will enable dynamic run-time updates of the server agents configuration according
# to current state of manifest file and separate agents registry files.
# Both manifest file and agent registry files could be modified (edited),
# agent registry files could be added or deleted from registry directory
# with corresponding changes in manifest file.
# Update will be done every AGENT_MANIFEST_UPDATE_PERIOD_SECONDS seconds;
# if value is not specified or <= 0, no such dynamic updates will be executed.
ENV AGENT_MANIFEST_UPDATE_PERIOD_SECONDS="0"

# By default, the HTTP service reports the neuro-san library pip version in its health-check response.
# It is possible to add other libraries to those results by listing them within this env var
# below and separating them with spaces, like this: "langchain openai".
# Sometimes it is useful to report a library version explicitly when they are not actually
# pip-installed (for instance when building a container from your own source, it's the
# tag of your repo that you care about.)  In that case you can add an entry with its version
# after a colon, like this: "my_repo:1.2.3".
# You can combine these too, like this: "langchain openai my_repo:1.2.3"
ENV AGENT_VERSION_LIBS=""

# A space-delimited list of http metadata request keys to forward to tracing/Observability
# infrastructure. When not set, this defaults to the value provided by
# AGENT_USAGE_LOGGER_METADATA or AGENT_FORWARDED_REQUEST_METADATA.
ENV AGENT_TRACING_METADATA_REQUEST_KEYS=""

# A space-delimited list of environment variables to be forwarded to observability tracing metadata.
# The defaults given here are standard Kubernetes environment variables for any given deployment pod.
# Only environment variables that are set to something other than the empty string will be forwarded.
ENV AGENT_TRACING_METADATA_ENV_VARS="POD_NAME POD_NAMESPACE POD_IP NODE_NAME"

# Size of backlog for TCP connections to http server.
# Sets the maximum number of pending TCP connections waiting to be accepted by the server.
# Impact:
# Higher values allow the kernel to queue more incoming connections during traffic spikes,
# reducing the chance of refused connections.
ENV AGENT_HTTP_CONNECTIONS_BACKLOG="128"

# Sets the maximum idle time (in seconds) before Tornado closes a keep-alive connection.
# Impact:
# Shorter timeouts free up resources faster under high load.
# Longer timeouts reduce reconnections for clients that make periodic requests.
ENV AGENT_HTTP_IDLE_CONNECTIONS_TIMEOUT="3600"

# Forks multiple worker processes, each with its own Tornado event loop, all sharing the same listening socket.
# Impact:
# Allows utilization of multiple CPU cores.
# Improves concurrency without blocking a single IOLoop.
# Typical Usage:
#   Value of 0 → Automatically spawns one process per CPU core.
#   Positive integer (N) → Manually specifies number of worker processes.
# The developer-oriented default is 1, but we set to 0 here to allow pod CPU configuration
# to dictate the number of server instance processes.
# Note 7/7/2026: If your installation requires temporary agent networks (aka Reservations),
# the server systems in place are not yet suitable for the multi-process operation
# that is implied by a value that is not 1.
ENV AGENT_HTTP_SERVER_INSTANCES="0"

# If set to a value>0, will start periodic logging of currently used
# run-time server resources:
# open file descriptors;
# open connections for server port.
# Logging period is specified in seconds.
ENV AGENT_HTTP_RESOURCES_MONITOR_INTERVAL="0"

# Interval in seconds between HTTP keep-alive messages sent to streaming clients
# to keep the connection alive during long quiet periods. This is important
# when intermediaries (nginx, load balancers, AWS ALB) or clients would otherwise
# drop an idle HTTP connection (commonly after ~60s) before the agent produces
# its next streamed message. The keep-alive message only fires when the stream has been
# quiet for approximately the full interval; real message traffic suppresses it.
# A value of 0 (the default) disables the keep-alive messages entirely.
# Typical production value is 25-30 (under the 60s defaults of common proxies).
ENV AGENT_STREAM_KEEP_ALIVE_WITH_PROGRESS_INTERVAL_SECONDS=0

# When any particular CodedTool execution takes longer than this many seconds,
# the system issues a message in the log.  This is very useful for determining
# where your scale-up problems are with particular networks.  The default value of
# 0 disables this feature.
ENV AGENT_TOOL_EXECUTION_LOG_THRESHOLD_SECONDS=0

# Optional URL describing how the server is to be referenced by the outside world.
# This is useful when a server is behind a load-balancer as part of a larger cluster.
ENV AGENT_EXTERNAL_SERVER_URL=""

# A reference to a Python class that can be used to store temporary agent references
# External to the server, so other replicated pods can pick them up.
# This class must have a no-args constructor and implement the
# neuro_san.internals.interfaces.ReservationsStorage interface.
# When not set, this defaults to a null implementation.
# A simple default implementation is provided by the class
# "neuro_san.service.watcher.temp_networks.s3_reservations_storage.S3ReservationsStorage"
ENV AGENT_EXTERNAL_RESERVATIONS_STORAGE=""

# When the AGENT_EXTERNAL_RESERVATIONS_STORAGE (immediately above) is set to the
# S3ReservationsStorage class mentioned there, this env var must be set to the S3 Bucket
# to use for cross-pod reservations storage.
ENV AGENT_RESERVATIONS_S3_BUCKET=""

# If AGENT_EXTERNAL_RESERVATIONS_STORAGE is set,
# then this parameter specifies the period in seconds for checking the external storage for expired reservations.
# Value of 0 means no periodic checks will be performed by the service,
# in this case it is expected that the external storage itself will handle expired reservations,
# or it will be done on demand by other tools.
ENV AGENT_RESERVATIONS_EXTERNAL_STORAGE_CHECK_PERIOD_SECONDS="0"

# The maximum number of temporary agent networks that will be kept internally
# in service memory at the same time. If this limit is reached,
# the oldest temporary networks (by access time) will be evicted.
# 0 or negative value means unlimited.
ENV AGENT_MAX_TEMP_NETWORKS="0"

# A hocon file with MCP servers information to be used by LangChainMcpAdapter
# for connecting to external MCP servers with authentication and tool filtering.
ENV MCP_SERVERS_INFO_FILE=""

# When set, this parameter enables MCP service protocol for running neuro-san server.
# Service endpoint is http://host:port/mcp
# (neuro-san own http API is also enabled in this case)
ENV AGENT_MCP_ENABLE="true"

# When set, this parameter will only enable MCP service protocol for running neuro-san server,
# while disabling neuro-san own http API.
ENV AGENT_MCP_ONLY="false"

#
# Server Hardening
#

# When set to "true", this parameter requires https for internal agent session communication.
# The default is "true". Developers should set this to false to work locally without acquiring certificates.
# Strongly consider keeping this on for production deployments.
ENV AGENT_SESSION_REQUIRE_HTTPS="true"

# When set to "false", this parameter will squelch the logging of sensitive information
# as flagged by static analysis (SAST) tools.
# The default is "false". Developers should set this to true to work locally with reasonable failure information.
# Strongly consider keeping this off for production deployments.
ENV LEAF_LOG_SENSITIVE="false"

#
# Authorization
#

# What class neuro-san server should use for authorization
# When not set (the default) the server uses an implementation for the Authorizer
# that effectively lets all requests for all users through.
# We offer the following implementations:
#   neuro_san.internals.authorization.null.always_yes_authorizer.AlwaysYesAuthorizer (default)
#   neuro_san.internals.authorization.null.always_no_authorizer.AlwaysNoAuthorizer
#   neuro_san.internals.authorization.openfga.open_fga_authorizer.OpenFgaAuthorizer
# Feel free to make your own as long as it derives from this interface:
#   neuro_san.internals.authorization.interfaces.authorizer.Authorizer
# Note that authorization (the ability to anwer the question "Does Actor X have Permission Y on Resource Z?")
# is not to be confused with authentication (the ability to answer the question "Is Actor X who they say they are?")
# Authentication is typically done outside a neuro-san server in a cluster load-balancer (for instance).
ENV AGENT_AUTHORIZER=""

# The request metadata field to use as the actor id for authorization
ENV AGENT_AUTHORIZER_ACTOR_ID_METADATA_KEY="user_id"

# See authorization logging.
# In production you would not want to set this at all.
# For debugging you might want to set this to "true".
ENV AGENT_DEBUG_AUTH=""

# The Actor type sent to the Authorizer
# This typically corresponds to a specific type set up in the authorization policy
ENV AGENT_AUTHORIZER_ACTOR_KEY="User"

# The Resource type sent to the Authorizer
# This typically corresponds to a specific type set up in the authorization policy
ENV AGENT_AUTHORIZER_RESOURCE_KEY="AgentNetwork"

# The Relation type sent to the Authorizer used to judge whether the Actor has permission to access the Resource.
# This typically corresponds to a specific relation set up in the authorization policy
# Typically "read" from CRUD-based permissions.
ENV AGENT_AUTHORIZER_ALLOW_RELATION="read"

# Whether to enable run-time statistics endpoints for neuro-san server as a whole.
# These endpoints can be used to get information about the server's current resource usage
# and also to control run-time service profiler.
ENV ENABLE_RUN_TIME_STATISTICS="false"

# Below: Env vars specific to OpenFgaAuthorizer

# Where the OpenFGA HTTP server is running for the OpenFgaAuthorizer
# Typical development example might be "http://localhost:8082"
ENV FGA_API_URL=""

# The file containing the authorization policy for the OpenFgaAuthorizer
# This is a path to a json file that has been compiled from a .fga policy file using the fga CLI tool.
ENV FGA_POLICY_FILE=""

# The name of the authorization store to use
# Typically "default"
ENV FGA_STORE_NAME=""


ENTRYPOINT ["/bin/bash", "-c", "exec ${APP_ENTRYPOINT}"]
