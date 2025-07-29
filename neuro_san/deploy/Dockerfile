
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
ARG PACKAGE_INSTALL=/usr/local/lib/python3.12/site-packages

# Stage 1: Builder Stage - Use our python base image for installations
# Set python image as base image
FROM python:3.12-slim as builder

# Set the shell and options per hadolint recommendations
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Reset to the root directory
WORKDIR /

# App-specific constants
ENV USERNAME=neuro-san
ENV APP_HOME=/usr/local/${USERNAME}
ENV APP_SOURCE=${APP_HOME}/myapp
ENV PIP3_VERSION=25.0.1

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
ENV USERNAME=neuro-san
ENV APP_HOME=/usr/local/${USERNAME}
ENV APP_SOURCE=${APP_HOME}/myapp

RUN \
    useradd -ms /bin/bash -d ${APP_HOME} -u 1001 ${USERNAME} \
    && echo ${USERNAME}:pw | chpasswd \
    && mkdir -p ${APP_HOME}/.ssh \
    && chown -R ${USERNAME}: ${APP_HOME} \
    && chown -R ${USERNAME}: /usr/local/ \
    && chown -R ${USERNAME}: /var/log \
    && mkdir -p ${APP_SOURCE}

# This is the port the service will accept grpc requests on.
# This should be consistent with the main port for the service as described
# in any kubernetes <service>.yaml file
# This port number is also mentioned as AGENT_PORT below
# and ServiceAgentSession.DEFAULT_PORT
# In order to be self-discovered by supporting build/run scripts this must
# be the first port exposed in the Dockerfile.
EXPOSE 30011

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
COPY ./neuro_san/registrie[s] ./registrie[s] ${APP_SOURCE}/registries
COPY ./neuro_san/coded_tool[s] ./coded_tool[s] ${APP_SOURCE}/coded_tools

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
ENV PACKAGE_INSTALL=${PACKAGE_INSTALL}
ENV PACKAGE_DEPLOY=${PACKAGE_INSTALL}/neuro_san/deploy
ENV APP_ENTRYPOINT=${PACKAGE_DEPLOY}/entrypoint.sh

ARG NEURO_SAN_VERSION

#
# Server configuration
#

# Where to find the tool registry manifest file which lists all the agent hocon
# files to serve up from this server instance.
ENV AGENT_MANIFEST_FILE=${APP_SOURCE}/registries/manifest.hocon

# An llm_info hocon file with user-provided llm descriptions that are to be used
# in addition to the neuro-san defaults.
ENV AGENT_LLM_INFO_FILE=""

# A toolbox_info hocon file with user-provided base tool and coded tool
# descriptions that are to be used in addition to the neuro-san defaults.
ENV AGENT_TOOLBOX_INFO_FILE=""

# Where to find the classes for CodedTool class implementations
# that are used by specific agent networks.
ENV AGENT_TOOL_PATH=${APP_SOURCE}/coded_tools

# Where to find the configuration file for Python logging.
# See https://docs.python.org/3/library/logging.config.html#dictionary-schema-details
# as to how this file can be configured for your own needs.  Examples there are provided in YAML,
# but these can be easily translated to JSON (which we prefer).
# Another good resource: https://docs.python.org/3/howto/logging-cookbook.html
ENV AGENT_SERVICE_LOG_JSON=${PACKAGE_DEPLOY}/logging.json

# Threshold for logging.
# See https://docs.python.org/3/library/logging.html#logging.Handler.setLevel
# and https://docs.python.org/3/library/logging.html#logging-levels for details.
ENV AGENT_SERVICE_LOG_LEVEL="DEBUG"

# The name of the service for grpc health reporting purposes
ENV AGENT_SERVER_NAME="neuro-san.Agent"

# Name of the service as seen in logs
ENV AGENT_SERVER_NAME_FOR_LOGS="Agent Server"

# A space-delimited list of http metadata request keys to forward to logs/other requests
# You can see how these are used in the AGENT_SERVICE_LOG_JSON file (see above) and
# customize this and the AGENT_SERVER_LOG_JSON file to your needs.
# Note that any metadata key needs to be all lowercase.
ENV AGENT_FORWARDED_REQUEST_METADATA="request_id user_id"

# Port number for the grpc service endpoint
# If you are changing this, you should also change the first EXPOSE port above
# and when running your container locally be sure to have a -p <port>:<port> entry
# for it on your docker run command line.
ENV AGENT_PORT=30011

# Port number for http service endpoint
# If you are changing this, you should also change the second EXPOSE port above
# and when running your container locally be sure to have a -p <port>:<port> entry
# for it on your docker run command line.
ENV AGENT_HTTP_PORT=8080

# Maximm number of requests that can be served at the same time
ENV AGENT_MAX_CONCURRENT_REQUESTS 50

# Number of requests served before the server shuts down in an orderly fashion.
# This is useful for testing response handling in clusters with duplicated pods.
# A value of -1 indicates unlimited requests are handled.
ENV AGENT_REQUEST_LIMIT=-1

# If this value is specified and >0,
# it will enable dynamic run-time updates of the server agents configuration according
# to current state of manifest file and separate agents registry files.
# Both manifest file and agent registry files could be modified (edited),
# agent registry files could be added or deleted from registry directory
# with corresponding changes in manifest file.
# Update will be done every AGENT_MANIFEST_UPDATE_PERIOD_SECONDS seconds;
# if value is not specified or <= 0, no such dynamic updates will be executed.
ENV AGENT_MANIFEST_UPDATE_PERIOD_SECONDS=0

# By default, the HTTP service reports the neuro-san library pip version in its health-check response.
# It is possible to add other libraries to those results by listing them within this env var
# below and separating them with spaces, like this: "langchain openai".
# Sometimes it is useful to report a library version explicitly when they are not actually
# pip-installed (for instance when building a container from your own source, it's the
# tag of your repo that you care about.)  In that case you can add an entry with its version
# after a colon, like this: "my_repo:1.2.3".
# You can combine these too, like this: "langchain openai my_repo:1.2.3"
ENV AGENT_VERSION_LIBS=""

# A reference to a Python class that can be used to log per-user request information.
# This class must have a no-args constructor and implement the
# neuro_san.interfaces.usage_logger.UsageLogger interface.
# When not set, this defaults to a null implementation.
ENV AGENT_USAGE_LOGGER=""

# A space-delimited list of http metadata request keys to forward to the AGENT_USAGE_LOGGER
# described above. When not set, this defaults to the value provided by
# AGENT_FORWARDED_REQUEST_METADATA
ENV AGENT_USAGE_LOGGER_METADATA=""

ENTRYPOINT "${APP_ENTRYPOINT}"
