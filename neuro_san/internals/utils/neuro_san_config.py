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

        # Loading networks, LLM info and toolboxes.
        "registry": {
            # None falls back to registries/manifest.hocon (registry_manifest_restorer.py:87-90)
            "AGENT_MANIFEST_FILE": None,
            # registry_manifest_restorer.py:272
            "AGENT_MANIFEST_CONCURRENCY_CONTEXT": "thread",
            # None defers to the network's llm_info_file, then built-in defaults (default_llm_factory.py:100-108)
            "AGENT_LLM_INFO_FILE": None,
            # None defers to the network's toolbox_info_file, then built-in defaults (toolbox_factory.py:108-116)
            "AGENT_TOOLBOX_INFO_FILE": None,
            # activation_factory.py:190
            "AGENT_ACTIVATION_PREPPER_CLASSES": ""
        },

        # Finding and running coded tools.
        "tools": {
            # None falls back to neuro_san/coded_tools (activation_factory.py:87-91)
            "AGENT_TOOL_PATH": None,
            # abstract_class_activation.py:404
            "AGENT_TOOL_PATH_ONLY": "false",
            # fetched_agent_network_storage.py:209
            "AGENT_FETCHABLE_TOOL_SCHEMES": "",
            # abstract_class_activation.py:189
            "AGENT_TOOL_EXECUTION_LOG_THRESHOLD_SECONDS": "0"
        },

        # Chat sessions.
        "chat": {
            # data_driven_chat_session.py:72
            "AGENT_PROTECT_ORIGINAL_COPY": "true"
        },

        # How temporary networks are addressed.
        "reservations": {
            # agent_reservation.py:88
            "AGENT_EXTERNAL_SERVER_URL": None
        },

        # Metadata attached to LangChain traces.
        "tracing": {
            # neuro_san_runnable.py:200
            "AGENT_TRACING_METADATA_ENV_VARS": "POD_NAME POD_NAMESPACE POD_IP NODE_NAME",
            # None falls back to AGENT_FORWARDED_REQUEST_METADATA (neuro_san_runnable.py:204-205)
            "AGENT_TRACING_METADATA_REQUEST_KEYS": None,
            # Also read by service/main_loop; both readers default to this value (agent_server.py:25)
            "AGENT_FORWARDED_REQUEST_METADATA": "request_id user_id"
        }
    },

    # The neuro-san server process.
    "service": {

        # Process identity and lifecycle.
        "server": {
            # http_server.py:70
            "AGENT_SERVER_NAME": "neuro-san.Agent",
            # server_status.py:110
            "AGENT_VERSION_LIBS": None,
            # server_main_loop.py:123
            "AGENT_MANIFEST_UPDATE_PERIOD_SECONDS": "0"
        },

        # The HTTP listener.
        "http": {
            # agent_session_constants.py:26
            "AGENT_HTTP_PORT": "8080",
            # Old alias for AGENT_HTTP_PORT (server_main_loop.py:94-96)
            "AGENT_PORT": None,
            # http_server_config.py:28
            "AGENT_HEALTH_PROBE_PORT": "8081",
            # http_server_config.py:25
            "AGENT_HTTP_SERVER_INSTANCES": "1",
            # http_server_config.py:23
            "AGENT_HTTP_CONNECTIONS_BACKLOG": "128",
            # http_server_config.py:24
            "AGENT_HTTP_IDLE_CONNECTIONS_TIMEOUT": "3600",
            # http_server_config.py:26
            "AGENT_HTTP_RESOURCES_MONITOR_INTERVAL": "0",
            # Any value enables (base_request_handler.py:81)
            "AGENT_ALLOW_CORS_HEADERS": None,
            # None falls back to api/grpc/agent_service.json (server_main_loop.py:238)
            "AGENT_OPENAPI_SPEC": None
        },

        # The MCP service.
        "mcp": {
            # server_main_loop.py:156
            "AGENT_MCP_ENABLE": "true",
            # server_main_loop.py:159
            "AGENT_MCP_ONLY": "false"
        },

        # Concurrency and request lifetime.
        "limits": {
            # http_server.py:73
            "AGENT_MAX_CONCURRENT_REQUESTS": "0",
            # None uses the ThreadPoolExecutor default (server_context.py:114-116)
            "AGENT_MAX_WORKERS_PER_REQUEST": None,
            # http_server.py:78
            "AGENT_REQUEST_LIMIT": "1000000",
            # http_server_config.py:27
            "AGENT_STREAM_KEEP_ALIVE_WITH_PROGRESS_INTERVAL_SECONDS": "0",
            # server_main_loop.py:151
            "AGENT_MAX_TEMP_NETWORKS": "0"
        },

        # The pluggable authorizer.
        "authorization": {
            # None disables authorization (authorizer_factory.py:41-42)
            "AGENT_AUTHORIZER": None,
            # agent_authorization_policy.py:49
            "AGENT_AUTHORIZER_ACTOR_KEY": "User",
            # agent_authorization_policy.py:50
            "AGENT_AUTHORIZER_ACTOR_ID_METADATA_KEY": "user_id",
            # agent_authorization_policy.py:51
            "AGENT_AUTHORIZER_RESOURCE_KEY": "AgentNetwork",
            # agent_authorization_policy.py:52, permission.py:28
            "AGENT_AUTHORIZER_ALLOW_RELATION": "read",
            # "hard" also fails on unauthorized (open_fga_authorizer.py:47-49)
            "AGENT_DEBUG_AUTH": None
        },

        # Where temporary networks are stored.
        "reservations": {
            # temp_network_storage_updater.py:88
            "AGENT_EXTERNAL_RESERVATIONS_STORAGE": "",
            # external_storage_util.py:42
            "AGENT_RESERVATIONS_EXTERNAL_STORAGE_CHECK_PERIOD_SECONDS": "0",
            # local_reservations_storage.py:105
            "AGENT_RESERVATIONS_LOCAL_PATH": "",
            # s3_reservations_writer.py:74
            "AGENT_RESERVATIONS_S3_BUCKET": "",
            # azure_blob_reservations_writer.py:57
            "AGENT_RESERVATIONS_AZURE_CONTAINER": ""
        },

        # Service logs and redaction.
        "logging": {
            # None falls back to deploy/logging.hocon (logging_config_restorer.py:46-47)
            "AGENT_SERVICE_LOG_JSON": None,
            # leaf-common logging_setup.py:50,200
            "AGENT_SERVICE_LOG_LEVEL": "DEBUG",
            # http_server.py:71
            "AGENT_SERVER_NAME_FOR_LOGS": "Agent Server",
            # None means no redaction (agent_server_logging.py:93-94)
            "AGENT_REQUEST_LOGGING_INPUT_SLICE": None
        },

        # Event-loop profiling and LLM traffic tracing.
        "diagnostics": {
            # http_server.py:299
            "AGENT_ASYNCIO_DEBUG": "false",
            # http_server.py:302
            "AGENT_ASYNCIO_SLOW_CALLBACK_DURATION_MS": "100",
            # http_server.py:344
            "AGENT_LOOP_TIMELINE": "false",
            # loop_timeline_tracer.py:78
            "AGENT_LOOP_TIMELINE_MAX_EVENTS": "100000",
            # http_server.py:357
            "AGENT_LOOP_TIMELINE_DUMP_PATH": "",
            # http_server.py:391
            "AGENT_HTTP_LLM_TRACE": "false",
            # http_server.py:395
            "AGENT_HTTP_LLM_TRACE_INCLUDE_BODIES": "false",
            # http_server.py:397
            "AGENT_HTTP_LLM_TRACE_CHUNKS": "false"
        }
    },

    # Client-side connections to a server.
    "session": {
        "security": {
            # abstract_http_service_agent_session.py:99
            "AGENT_SESSION_REQUIRE_HTTPS": "false"
        }
    },

    "tests": {
        # The data-driven test driver.
        "driver": {
            # None writes no thinking files (data_driven_tests_driver.py:514-515)
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

        self.config: Dict[str, Any] = copy(DEFAULT_CONFIG)
        self.extractor: DictionaryExtractor = None

        self.register(EnvironmentConfigFilter())

        self.config = self.filter_config(self.config)
        self.extractor = DictionaryExtractor(self.config)

    @staticmethod
    def get(key: str) -> Optional[str]:
        """
        Given the fully-qualified string key, return the value from the configuation

        :param key: The fully-qualified key from the config
        :return: The value in the config.
        """
        value: Optional[str] = _INSTANCE.get_fully_qualified(key)
        return value

    def get_fully_qualified(self, key: str) -> Optional[str]:
        """
        Given the fully-qualified string key, return the value from the configuation

        :param key: The fully-qualified key from the config
        :return: The value in the config.
        """
        value: Optional[str] = self.extractor.get(key)
        return value


# Singleton. Access via NeuroSanConfig.get()
_INSTANCE: NeuroSanConfig = NeuroSanConfig()
