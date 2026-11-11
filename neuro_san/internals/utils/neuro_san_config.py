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

from os import environ

from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from leaf_common.config.config_filter_chain import ConfigFilterChain
from leaf_common.config.config_util import ConfigUtil
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

        "hardening": {
            # A little bit faster to run with this false
            "AGENT_PROTECT_ORIGINAL_COPY": "true",
            "AGENT_LOCKDOWN_ENV": "false"
        },

        # Loading LLM info.
        "llms": {
            # None defers to the network's llm_info_file, then built-in defaults
            "AGENT_LLM_INFO_FILE": None
        },

        # Loading networks.
        "registry": {
            "AGENT_ACTIVATION_PREPPER_CLASSES": "",
            "AGENT_MANIFEST_CONCURRENCY_CONTEXT": "thread",
            # None falls back to registries/manifest.hocon
            "AGENT_MANIFEST_FILE": None
        },

        # Finding and running coded tools, and loading toolboxes.
        "tools": {
            "AGENT_FETCHABLE_TOOL_SCHEMES": "",
            # None defers to the network's toolbox_info_file, then built-in defaults
            "AGENT_TOOLBOX_INFO_FILE": None,
            "AGENT_TOOL_EXECUTION_LOG_THRESHOLD_SECONDS": "0",
            # None falls back to neuro_san/coded_tools
            "AGENT_TOOL_PATH": None,
            "AGENT_TOOL_PATH_ONLY": "false"
        },

        # Metadata attached to LangChain traces.
        "tracing": {
            # Also read by service/main_loop; both readers default to this value
            "AGENT_FORWARDED_REQUEST_METADATA": "request_id user_id",
            "AGENT_TRACING_METADATA_ENV_VARS": "POD_NAME POD_NAMESPACE POD_IP NODE_NAME",
            # None falls back to AGENT_FORWARDED_REQUEST_METADATA
            "AGENT_TRACING_METADATA_REQUEST_KEYS": None
        }
    },

    # The neuro-san server process.
    "service": {

        # The pluggable authorizer.
        "authorization": {
            # None disables authorization
            "AGENT_AUTHORIZER": None,
            "AGENT_AUTHORIZER_ACTOR_ID_METADATA_KEY": "user_id",
            "AGENT_AUTHORIZER_ACTOR_KEY": "User",
            "AGENT_AUTHORIZER_ALLOW_RELATION": "read",
            "AGENT_AUTHORIZER_RESOURCE_KEY": "AgentNetwork",
            # "hard" also fails on unauthorized
            "AGENT_DEBUG_AUTH": None
        },

        # Event-loop profiling and LLM traffic tracing.
        "diagnostics": {
            "AGENT_ASYNCIO_DEBUG": "false",
            "AGENT_ASYNCIO_SLOW_CALLBACK_DURATION_MS": "100",
            "AGENT_HTTP_LLM_TRACE": "false",
            "AGENT_HTTP_LLM_TRACE_CHUNKS": "false",
            "AGENT_HTTP_LLM_TRACE_INCLUDE_BODIES": "false",
            "AGENT_LOOP_TIMELINE": "false",
            "AGENT_LOOP_TIMELINE_DUMP_PATH": "",
            "AGENT_LOOP_TIMELINE_MAX_EVENTS": "100000",
            "ENABLE_RUN_TIME_STATISTICS": "false",          # No AGENT_ prefix
            "AGENT_ENABLE_EVENT_LOOP_STATISTICS": "false",
            "AGENT_SHOW_ABSENT_METADATA": "false"
        },

        # The HTTP listener.
        "http": {
            # Any value enables
            "AGENT_ALLOW_CORS_HEADERS": None,
            # None falls back to HttpServerConfig.http_probe_port
            "AGENT_HEALTH_PROBE_PORT": None,
            "AGENT_HTTP_CONNECTIONS_BACKLOG": "128",
            "AGENT_HTTP_IDLE_CONNECTIONS_TIMEOUT": "3600",
            # None falls back to AGENT_PORT
            "AGENT_HTTP_PORT": None,
            "AGENT_HTTP_RESOURCES_MONITOR_INTERVAL": "0",
            "AGENT_HTTP_SERVER_INSTANCES": "1",
            # None falls back to api/grpc/agent_service.json
            "AGENT_OPENAPI_SPEC": None,
            # Old alias for AGENT_HTTP_PORT, which also holds the final default
            "AGENT_PORT": "8080"
        },

        # Concurrency and request lifetime.
        "limits": {
            "AGENT_MAX_CONCURRENT_REQUESTS": "0",
            "AGENT_MAX_TEMP_NETWORKS": "0",
            # None uses the ThreadPoolExecutor default
            "AGENT_MAX_WORKERS_PER_REQUEST": None,
            "AGENT_REQUEST_LIMIT": "1000000",
            "AGENT_STREAM_KEEP_ALIVE_WITH_PROGRESS_INTERVAL_SECONDS": "0"
        },

        # Service logs and redaction.
        "logging": {
            # None means no redaction
            "AGENT_REQUEST_LOGGING_INPUT_SLICE": None,
            "AGENT_SERVER_NAME_FOR_LOGS": "Agent Server",
            # None falls back to deploy/logging.hocon
            "AGENT_SERVICE_LOG_JSON": None,
            # The default here is merely for consolidated documentation at the moment.
            # The code actually passes the env var name to another lower-level method which always
            # reads the value from the env var.
            "AGENT_SERVICE_LOG_LEVEL": "DEBUG"
        },

        # The MCP service.
        "mcp": {
            "AGENT_MCP_ENABLE": "true",
            "AGENT_MCP_ONLY": "false"
        },

        # Where temporary networks are stored.
        "reservations": {
            "AGENT_EXTERNAL_RESERVATIONS_STORAGE": "",
            "AGENT_EXTERNAL_SERVER_URL": None,
            "AGENT_RESERVATIONS_AZURE_CONTAINER": "",
            # The default here is merely for consolidated documentation at the moment.
            # The code actually passes the env var name to another lower-level method which always
            # reads the value from the env var. In this case there are writes as well (ick!).
            "AGENT_RESERVATIONS_EXTERNAL_STORAGE_CHECK_PERIOD_SECONDS": "0",
            "AGENT_RESERVATIONS_LOCAL_PATH": "",
            "AGENT_RESERVATIONS_S3_BUCKET": ""
        },

        # Process identity and lifecycle.
        "server": {
            "AGENT_MANIFEST_UPDATE_PERIOD_SECONDS": "0",
            "AGENT_SERVER_NAME": "neuro-san.Agent",
            "AGENT_VERSION_LIBS": None
            # Note: More constants exist in ServerMainLoop and HttpServerConfig.
        }
    },

    # Client-side connections to a server.
    "session": {
        "security": {
            "AGENT_SESSION_REQUIRE_HTTPS": "false"
            # Documented in SAST_FALSE_POSITIVES.md
            # MAX_AGENTS_FROM_EXTERNAL_SERVER - does not have AGENT_ prefix
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
    This will allow us to get config from a dictionary, the environment and also potentially do overlays
    from files.

    This is a singleton whose values can be loaded/determined at first-mention.
    By default, any value can be overridden by its corresponding environment variable value
    at run-time evaluation.

    However with "AGENT_LOCKDOWN_ENV" set to "true" (not the default), the environment is only
    ever read once at startup.  With this on, if a rogue coded tool decides to try to change one
    of these via env var, it will fail (good!).
    """

    def __init__(self):
        """
        Constructor
        """
        super().__init__()

        self.config: Dict[str, Any] = None
        self.extractor: DictionaryExtractor = None
        self.default_extractor: DictionaryExtractor = DictionaryExtractor(DEFAULT_CONFIG)
        self.lockdown: bool = False

        self.register(EnvironmentConfigFilter())

        self._load()

    @staticmethod
    def get(key: str) -> Optional[str]:
        """
        Given the fully-qualified string key, return the value from the configuration

        :param key: The fully-qualified key from the config
        :return: The string value in the config.
        """
        # pylint: disable=protected-access
        value: Optional[str] = _INSTANCE._internal_get(key)
        return value

    @staticmethod
    def get_non_empty(key: str) -> Optional[str]:
        """
        Given the fully-qualified string key, return the value from the configuration,
        treating an empty value the same as an unset one.

        get() keeps a variable that is set to an empty string, because some variables
        mean something when set but empty. Use this method instead for variables where
        an empty value means "use the default".

        :param key: The fully-qualified key from the config
        :return: The value in the config, or the default from DEFAULT_CONFIG
                 when the value is empty.
        """
        # pylint: disable=protected-access
        value: Optional[str] = _INSTANCE._internal_get_non_empty(key)
        return value

    @staticmethod
    def get_bool(key: str) -> bool:
        """
        :param key: The fully-qualified key from the config
        :return: True the value for the key is to be considered True.
                 False otherwise.
        """
        # pylint: disable=protected-access
        bool_value: bool = _INSTANCE._internal_get_bool(key)
        return bool_value

    def _load(self):
        """
        Builds the configuration from DEFAULT_CONFIG, filtered through the registered filters.
        """
        self.config = DEFAULT_CONFIG
        self.config = self.filter_config(self.config)
        self.extractor = DictionaryExtractor(self.config)
        self.lockdown = self._internal_get_bool("internals.hardening.AGENT_LOCKDOWN_ENV")

    def _internal_get(self, key: str) -> Optional[str]:
        """
        Given the fully-qualified string key, return the value from the configuration

        :param key: The fully-qualified key from the config
        :return: The value in the config.  Most often this is a string or None, however
                    it is possible to return entire sections of the configuration dictionary
                    (much less common).
        """
        # pylint: disable=protected-access
        value: Optional[str] = self._get_fully_qualified(key)
        if not self._is_lockdown():
            key_split: List[str] = key.split(".")
            env_key: str = key_split[-1]
            # Not EnvironmentUtil.getenv(), which also replaces an empty value with the default.
            value = environ.get(env_key, value)
        return value

    def _internal_get_non_empty(self, key: str) -> Optional[str]:
        """
        Given the fully-qualified string key, return the value from the configuration,
        treating an empty value the same as an unset one.

        :param key: The fully-qualified key from the config
        :return: The value in the config, or the default from DEFAULT_CONFIG
                 when the value is empty.
        """
        value: Optional[str] = self._internal_get(key)
        if value is not None and len(value) == 0:
            value = self._get_default(key)
        return value

    def _internal_get_bool(self, key: str) -> bool:
        """
        :param key: The fully-qualified key from the config
        :return: True the value for the key is to be considered True.
                 False otherwise. An empty value uses the default from DEFAULT_CONFIG.
        """
        # Use _internal_get_non_empty() so that unset/empty values use the defaults.
        value: Optional[str] = self._internal_get_non_empty(key)
        bool_value: bool = ConfigUtil.is_true(value)
        return bool_value

    def _get_fully_qualified(self, key: str) -> Optional[str]:
        """
        Given the fully-qualified string key, return the value from the configuration

        :param key: The fully-qualified key from the config
        :return: The value in the config.
        """
        value: Optional[str] = self.extractor.get(key)
        return value

    def _get_default(self, key: str) -> Optional[str]:
        """
        Given the fully-qualified string key, return the default from DEFAULT_CONFIG,
        ignoring the environment.

        :param key: The fully-qualified key from the config
        :return: The default value for the key
        """
        value: Optional[str] = self.default_extractor.get(key)
        return value

    def _is_lockdown(self) -> bool:
        """
        :return: True if the environment is locked down/forbidden from further env lookups.
                 False otherwise
        """
        return self.lockdown

    @staticmethod
    def reset_for_testing():
        """
        Reloads the singleton configuration so that it reflects the current environment.
        The configuration is read at least once at import time, so tests that change environment
        variables call this after making the change and again after undoing it
        if AGENT_LOCKDOWN_ENV is enabled.
        """
        # pylint: disable=protected-access
        _INSTANCE._load()


# Singleton. Access via NeuroSanConfig.get()
_INSTANCE: NeuroSanConfig = NeuroSanConfig()
