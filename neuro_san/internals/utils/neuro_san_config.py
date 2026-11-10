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
from __future__ import annotations

from typing import Any
from typing import Dict
from typing import Optional

from copy import copy

from leaf_common.config.config_filter_chain import ConfigFilterChain
from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.internals.utils.environment_config_filter import EnvironmentConfigFilter


# Structure is <category>.<subgroup>.<AGENT_* env var name> = <default value>.
# Defaults are strings because environment variables are strings.
# A None default means there is no literal default: either the feature is off
# when the variable is unset, or the code computes a fallback (described in the comment).
DEFAULT_CONFIG: Dict[str, Any] = {

    # The agent runtime, which runs with or without a server.
    # Anything read at least in neuro_san/internals lives here.
    "internals": {

        # Loading networks.
        "registry": {
            # None falls back to registries/manifest.hocon
            "AGENT_MANIFEST_FILE": None,
            "AGENT_MANIFEST_CONCURRENCY_CONTEXT": "thread",
            "AGENT_ACTIVATION_PREPPER_CLASSES": ""
        },

        # Loading LLM info.
        "llms": {
            # None defers to the network's llm_info_file, then built-in defaults
            "AGENT_LLM_INFO_FILE": None
        },

        # Finding and running coded tools, and loading toolboxes.
        "tools": {
            # None falls back to neuro_san/coded_tools
            "AGENT_TOOL_PATH": None,
            "AGENT_TOOL_PATH_ONLY": "false",
            "AGENT_FETCHABLE_TOOL_SCHEMES": "",
            "AGENT_TOOL_EXECUTION_LOG_THRESHOLD_SECONDS": "0",
            # None defers to the network's toolbox_info_file, then built-in defaults
            "AGENT_TOOLBOX_INFO_FILE": None
        },

        # Chat sessions.
        "chat": {
            "AGENT_PROTECT_ORIGINAL_COPY": "true"
        },

        # How temporary networks are addressed.
        "reservations": {
            "AGENT_EXTERNAL_SERVER_URL": None
        },

        # Metadata attached to LangChain traces.
        "tracing": {
            "AGENT_TRACING_METADATA_ENV_VARS": "POD_NAME POD_NAMESPACE POD_IP NODE_NAME",
            # None falls back to AGENT_FORWARDED_REQUEST_METADATA
            "AGENT_TRACING_METADATA_REQUEST_KEYS": None,
            # Also read by service/main_loop; both readers default to this value
            "AGENT_FORWARDED_REQUEST_METADATA": "request_id user_id"
        }
    },

    # The neuro-san server process.
    "service": {

        # Process identity and lifecycle.
        "server": {
            "AGENT_SERVER_NAME": "neuro-san.Agent",
            "AGENT_VERSION_LIBS": None,
            "AGENT_MANIFEST_UPDATE_PERIOD_SECONDS": "0"
        },

        # The HTTP listener.
        "http": {
            # None falls back to AGENT_PORT
            "AGENT_HTTP_PORT": None,
            # Old alias for AGENT_HTTP_PORT, which also holds the final default
            "AGENT_PORT": "8080",
            "AGENT_HEALTH_PROBE_PORT": "8081",
            "AGENT_HTTP_SERVER_INSTANCES": "1",
            "AGENT_HTTP_CONNECTIONS_BACKLOG": "128",
            "AGENT_HTTP_IDLE_CONNECTIONS_TIMEOUT": "3600",
            "AGENT_HTTP_RESOURCES_MONITOR_INTERVAL": "0",
            # Any value enables
            "AGENT_ALLOW_CORS_HEADERS": None,
            # None falls back to api/grpc/agent_service.json
            "AGENT_OPENAPI_SPEC": None
        },

        # The MCP service.
        "mcp": {
            "AGENT_MCP_ENABLE": "true",
            "AGENT_MCP_ONLY": "false"
        },

        # Concurrency and request lifetime.
        "limits": {
            "AGENT_MAX_CONCURRENT_REQUESTS": "0",
            # None uses the ThreadPoolExecutor default
            "AGENT_MAX_WORKERS_PER_REQUEST": None,
            "AGENT_REQUEST_LIMIT": "1000000",
            "AGENT_STREAM_KEEP_ALIVE_WITH_PROGRESS_INTERVAL_SECONDS": "0",
            "AGENT_MAX_TEMP_NETWORKS": "0"
        },

        # The pluggable authorizer.
        "authorization": {
            # None disables authorization
            "AGENT_AUTHORIZER": None,
            "AGENT_AUTHORIZER_ACTOR_KEY": "User",
            "AGENT_AUTHORIZER_ACTOR_ID_METADATA_KEY": "user_id",
            "AGENT_AUTHORIZER_RESOURCE_KEY": "AgentNetwork",
            "AGENT_AUTHORIZER_ALLOW_RELATION": "read",
            # "hard" also fails on unauthorized
            "AGENT_DEBUG_AUTH": None
        },

        # Where temporary networks are stored.
        "reservations": {
            "AGENT_EXTERNAL_RESERVATIONS_STORAGE": "",
            "AGENT_RESERVATIONS_EXTERNAL_STORAGE_CHECK_PERIOD_SECONDS": "0",
            "AGENT_RESERVATIONS_LOCAL_PATH": "",
            "AGENT_RESERVATIONS_S3_BUCKET": "",
            "AGENT_RESERVATIONS_AZURE_CONTAINER": ""
        },

        # Service logs and redaction.
        "logging": {
            # None falls back to deploy/logging.hocon
            "AGENT_SERVICE_LOG_JSON": None,
            "AGENT_SERVICE_LOG_LEVEL": "DEBUG",
            "AGENT_SERVER_NAME_FOR_LOGS": "Agent Server",
            # None means no redaction
            "AGENT_REQUEST_LOGGING_INPUT_SLICE": None
        },

        # Event-loop profiling and LLM traffic tracing.
        "diagnostics": {
            "AGENT_ASYNCIO_DEBUG": "false",
            "AGENT_ASYNCIO_SLOW_CALLBACK_DURATION_MS": "100",
            "AGENT_LOOP_TIMELINE": "false",
            "AGENT_LOOP_TIMELINE_MAX_EVENTS": "100000",
            "AGENT_LOOP_TIMELINE_DUMP_PATH": "",
            "AGENT_HTTP_LLM_TRACE": "false",
            "AGENT_HTTP_LLM_TRACE_INCLUDE_BODIES": "false",
            "AGENT_HTTP_LLM_TRACE_CHUNKS": "false"
        }
    },

    # Client-side connections to a server.
    "session": {
        "security": {
            "AGENT_SESSION_REQUIRE_HTTPS": "false"
        }
    },

    "tests": {
        # The data-driven test driver.
        "driver": {
            # None writes no thinking files
            "AGENT_TEST_THINKING_BASIS": None
        }
    }
}


class NeuroSanConfig(ConfigFilterChain):
    """
    Class from which to get configuration.
    This will allow us to get config from a dictionary, the environment and also
    potentially do overlays.
    """

    def __init__(self):
        """
        Constructor
        """
        super().__init__()

        self.config: Dict[str, Any] = None
        self.extractor: DictionaryExtractor = None

        self.register(EnvironmentConfigFilter())

        self._load()

    @staticmethod
    def get(key: str) -> Optional[str]:
        """
        Given the fully-qualified string key, return the value from the configuation

        :param key: The fully-qualified key from the config
        :return: The value in the config.
        """
        # pylint: disable=protected-access
        value: Optional[str] = _INSTANCE._get_fully_qualified(key)
        return value

    def _load(self):
        """
        Builds the configuration from DEFAULT_CONFIG, filtered through the registered filters.
        """
        self.config = copy(DEFAULT_CONFIG)
        self.config = self.filter_config(self.config)
        self.extractor = DictionaryExtractor(self.config)

    def _get_fully_qualified(self, key: str) -> Optional[str]:
        """
        Given the fully-qualified string key, return the value from the configuation

        :param key: The fully-qualified key from the config
        :return: The value in the config.
        """
        value: Optional[str] = self.extractor.get(key)
        return value

    @staticmethod
    def reset_for_testing():
        """
        Reloads the singleton configuration so that it reflects the current environment.
        The configuration is read once at import time, so tests that change environment
        variables call this after making the change and again after undoing it.
        """
        # pylint: disable=protected-access
        _INSTANCE._load()


# Singleton. Access via NeuroSanConfig.get()
_INSTANCE: NeuroSanConfig = NeuroSanConfig()
