
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
import os

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from logging import Logger
from logging import getLogger

from typing_extensions import override

from langchain_core.language_models.base import BaseLanguageModel

from leaf_common.config.config_util import ConfigUtil

from neuro_san.internals.run_context.langchain.llms.openai_llm_policy import OpenAILlmPolicy
from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler import PRICE_MODEL_METADATA_KEY
from neuro_san.internals.run_context.langchain.token_counting.llm_token_callback_handler import PROVIDER_METADATA_KEY


class AzureLlmPolicy(OpenAILlmPolicy):
    """
    LlmPolicy implementation for OpenAI models served by an Azure OpenAI resource.

    Azure's v1 API (https://learn.microsoft.com/en-us/azure/foundry/openai/api-version-lifecycle)
    serves the OpenAI request and response formats at {AZURE_OPENAI_ENDPOINT}/openai/v1/ for both
    Chat Completions and the Responses API, without an api-version query string. So this policy
    reuses the plain AsyncOpenAI client and the ChatOpenAI arguments of OpenAILlmPolicy, and only
    differs in three places:

        * Where requests go: the azure_endpoint of the llm_config with "/openai/v1/" appended, else the
          openai_api_base of the llm_config verbatim (the full base URL of a gateway), else the
          AZURE_OPENAI_ENDPOINT environment variable with "/openai/v1/" appended.
        * The credential: azure_ad_token / AZURE_OPENAI_AD_TOKEN when set, else openai_api_key /
          AZURE_OPENAI_API_KEY, else OPENAI_API_KEY. Azure's v1 API accepts an API key in the same
          Authorization: Bearer header the SDK sends for OpenAI, so no api-key header is needed.
        * The model: Azure routes by deployment, so the chat model is a plain ChatOpenAI whose model is
          deployment_name / AZURE_OPENAI_DEPLOYMENT_NAME, or the llm_info model name when neither is
          given. The OpenAI model behind the deployment (the llm_config's model_name) is not sent
          anywhere; it is handed to token accounting through the chat model's metadata, so the usage is
          priced by it and booked under "azure-openai". langchain's model-name rules therefore see the
          deployment name: a temperature other than 1 is dropped only for a deployment whose name starts
          with "gpt-5"; a gpt-5 deployment named any other way sends it as given and Azure rejects it.

    Configuration errors (no endpoint, no credential, no deployment) are raised as openai.OpenAIError,
    the same family the OpenAI SDK raises for a missing api_key, so that DefaultLlmFactory turns them
    into the friendly API-key guidance (see API_KEY_ERRORS there and ApiKeyErrorCheck).

    The llm_config keys of Azure's dated API (openai_api_version, openai_api_type, model_version) are
    still accepted so that existing configs load, but the v1 API has no use for them: they are ignored
    and warned about once.

    This class is a child of OpenAILlmPolicy, and inherits its implementation of
    create_http_client() and delete_resources().
    """

    # Path Azure's v1 API lives under, relative to the resource endpoint.
    V1_PATH: str = "/openai/v1"

    # llm_config keys of the dated Azure API that the v1 API has no use for.
    LEGACY_KEYS: Tuple[str, ...] = ("openai_api_version", "openai_api_type", "model_version")

    # Process-wide so the legacy-key warning appears once, not once per agent instantiation.
    legacy_keys_warned: bool = False

    @override
    def __init__(self, llm: BaseLanguageModel = None) -> None:
        """
        Constructor.

        :param llm: BaseLanguageModel
        """
        super().__init__(llm)
        self.logger: Logger = getLogger(self.__class__.__name__)

    def create_client(self, config: Dict[str, Any]) -> Any:
        """
        Creates the web client to used by a BaseLanguageModel to be
        constructed in the future.  Neuro SAN infrastructures prefers that this
        be an asynchronous client, however we realize some BaseLanguageModels
        do not support that (even though they should!).

        Implementations should retain any references to state that needs to be cleaned up
        in the delete_resources() method.

        :param config: The fully specified llm config
        :return: The web client that accesses the LLM.
                By default this is None, as many BaseLanguageModels
                do not allow a web client to be passed in as an arg.
        :raises OpenAIError: When no endpoint, credential or deployment can be found (see
                resolve_base_url(), resolve_credential() and resolve_deployment_name())
        """
        # Azure's v1 API serves the OpenAI wire format under {endpoint}/openai/v1/, so the plain
        # OpenAI SDK client is all it needs. Same lazy-loading resolver rigamarole as the other policies.

        # pylint: disable=invalid-name
        AsyncOpenAI = self.resolver.resolve_class_in_module("AsyncOpenAI",
                                                            module_name="openai",
                                                            install_if_missing="langchain-openai")

        # Resolve the configuration before opening anything: the factory drops a policy whose
        # create_client() raised without calling delete_resources(), so an httpx client opened
        # first would leak on a missing endpoint or credential.
        api_key: str = self.resolve_credential(config)
        base_url: str = self.resolve_base_url(config)
        default_headers: Dict[str, str] = self.build_default_headers(config)
        # The deployment is checked here for the same reason: create_llm() would only find it
        # missing once this client exists.
        self.resolve_deployment_name(config, self.model_name_from_config(config))

        self.create_http_client(config)

        client_args: Dict[str, Any] = {
            "api_key": api_key,
            "base_url": base_url,
            "organization": self.get_value_or_env(config, "openai_organization", "OPENAI_ORG_ID"),
            "timeout": config.get("request_timeout"),
            "default_headers": default_headers,
            "http_client": self.http_client,
        }
        # The SDK rejects max_retries=None outright (TypeError), so leave it out to get the SDK default.
        max_retries: Any = config.get("max_retries")
        if max_retries is not None:
            client_args["max_retries"] = max_retries

        self.async_openai_client = AsyncOpenAI(**client_args)

        # We retain the async_openai_client reference, but we hand back this reach-in
        # to pass to the BaseLanguageModel constructor.
        return self.async_openai_client.chat.completions

    def create_llm(self, config: Dict[str, Any], model_name: str, client: Any) -> BaseLanguageModel:
        """
        Create a BaseLanguageModel instance from the fully-specified llm config
        for the llm class that the implementation supports.  Chat models are usually
        per-provider, where the specific model itself is an argument to its constructor.

        :param config: The fully specified llm config
        :param model_name: The name of the model. For Azure this is the OpenAI model behind the
                deployment (the llm_info entry's use_model_name), or None for a deployment-only
                llm_config; it prices the usage and is the last-resort deployment name, but the
                request itself names the deployment.
        :param client: The web client to use (if any)
        :return: A BaseLanguageModel (can be Chat or LLM)
        :raises OpenAIError: When no deployment name can be resolved (see resolve_deployment_name())
        """
        # The plain ChatOpenAI is all Azure's v1 API needs once the client points at it and the model is
        # the deployment. Same lazy-loading resolver rigamarole as OpenAILlmPolicy.
        # pylint: disable=invalid-name
        ChatOpenAI = self.resolver.resolve_class_in_module("ChatOpenAI",
                                                           module_name="langchain_openai.chat_models.base",
                                                           install_if_missing="langchain-openai")

        self.warn_about_legacy_keys(config)

        deployment_name: str = self.resolve_deployment_name(config, model_name)

        llm = ChatOpenAI(
            async_client=client,
            root_async_client=self.async_openai_client,
            # Azure routes by deployment: this is what goes in the "model" field on both
            # /openai/v1/chat/completions and /openai/v1/responses. The OpenAI model behind it only
            # reaches token accounting, through the metadata below.
            model_name=deployment_name,
            metadata=self.build_accounting_metadata(deployment_name, model_name),
            temperature=config.get("temperature"),

            # Unlike OpenAILlmPolicy, the key and base URL are passed even when a client is given.
            # ChatOpenAI builds a synchronous SDK client of its own from these two fields (and an
            # asynchronous one when none is passed in); with None it would read OPENAI_API_KEY and
            # point at api.openai.com, which is never right for an Azure resource.
            openai_api_key=self.resolve_credential(config),
            openai_api_base=self.resolve_base_url(config),

            # This next group of params should always be None when we have a client
            openai_organization=self.get_value_or_env(config, "openai_organization",
                                                      "OPENAI_ORG_ID", client),
            openai_proxy=self.get_value_or_env(config, "openai_proxy",
                                               "OPENAI_PROXY", client),
            request_timeout=self.get_value_or_env(config, "request_timeout", None, client),
            max_retries=self.get_value_or_env(config, "max_retries", None, client),

            # Chat Completions only. langchain-openai rejects a Responses API request that carries
            # any of them, exactly as for the "openai" class; see docs/llm_info_hocon_reference.md.
            presence_penalty=config.get("presence_penalty"),
            frequency_penalty=config.get("frequency_penalty"),
            seed=config.get("seed"),
            logprobs=config.get("logprobs"),
            top_logprobs=config.get("top_logprobs"),
            logit_bias=config.get("logit_bias"),
            # Streaming is configurable via the "streaming" key in llm_config; defaults
            # to False so existing agents keep their long-standing non-streaming behavior.
            # We pass streaming explicitly (rather than relying on LangChain's default) so
            # that langchain_core._should_stream() picks up the configured value even when
            # a streaming-aware callback is attached to the run manager. Token usage is
            # collected from AIMessage.usage_metadata in LlmTokenCallbackHandler regardless
            # of streaming mode.
            streaming=ConfigUtil.get_bool(config, "streaming"),
            # n is intentionally not sent, for the same reason as in OpenAILlmPolicy: the API default
            # of 1 is all neuro-san consumes and the Responses API has no n parameter at all.
            top_p=config.get("top_p"),
            max_tokens=config.get("max_tokens"),  # This is always for output
            tiktoken_model_name=config.get("tiktoken_model_name"),
            # Only takes effect on Chat Completions: langchain-openai drops stop from Responses API
            # requests (the API has no such parameter) rather than failing.
            stop=config.get("stop"),

            # Reasoning models only. Set either "reasoning" or "reasoning_effort", not both:
            # see the same arguments in OpenAILlmPolicy for why.
            reasoning=config.get("reasoning"),
            reasoning_effort=config.get("reasoning_effort"),
            verbosity=config.get("verbosity"),

            # Endpoint selection and server-side storage, forwarded raw for the same reasons as in
            # OpenAILlmPolicy (a null must reach langchain as None). The "azure-openai" class inherits
            # the "openai" defaults, so Azure requests go to /openai/v1/responses unless an llm_config
            # says "use_responses_api": false. Azure's Responses API is not offered in every region and
            # not for every model (see docs/llm_info_hocon_reference.md).
            use_responses_api=config.get("use_responses_api"),
            store=config.get("store"),
            include=config.get("include"),

            # Explicitly False for the same reason as in OpenAILlmPolicy: reading the global verbose
            # value during concurrent initialization can trigger a langchain UserWarning.
            verbose=False,

            # Track streaming: emit token-usage frames only when streaming is enabled.
            stream_usage=ConfigUtil.get_bool(config, "streaming")
        )

        return llm

    @staticmethod
    def model_name_from_config(config: Dict[str, Any]) -> Optional[str]:
        """
        Reads the model name the way LlmPolicy.create_llm_resources_components() does before it calls
        create_llm(), so that create_client() checks the deployment against the same value.

        :param config: The fully specified llm config
        :return: model_name, model or model_id from the config, whichever is set first; None when none is
        """
        return config.get("model_name") or config.get("model") or config.get("model_id")

    @staticmethod
    def build_accounting_metadata(deployment_name: str, model_name: Optional[str]) -> Dict[str, Any]:
        """
        Builds the chat model metadata that tells LlmTokenCallbackHandler how to book Azure usage.

        The stock ChatOpenAI class would be booked under "openai", and Azure's Responses API names the
        deployment as the response model, which has no llm_info entry to price by. So the metadata names
        the "azure-openai" bucket and, when an OpenAI model is configured behind the deployment, that
        model as the one to price the usage by. A deployment-only llm_config gets no price hint, so the
        model the response names decides: the deployment echo on the Responses API has no price, while
        the OpenAI snapshot Chat Completions names is priced.

        :param deployment_name: The Azure deployment the requests name
        :param model_name: The OpenAI model behind it, or None when the llm_config gives none
        :return: The metadata dict to pass to the chat model
        """
        metadata: Dict[str, Any] = {PROVIDER_METADATA_KEY: "azure-openai"}
        if model_name and model_name != deployment_name:
            metadata[PRICE_MODEL_METADATA_KEY] = model_name
        return metadata

    def resolve_base_url(self, config: Dict[str, Any]) -> str:
        """
        Works out the base URL of the Azure OpenAI v1 API to send requests to.

        Values from the llm_config win over the environment, as they do for the credential and the
        deployment name: azure_endpoint first, then openai_api_base (the full base URL of an
        OpenAI-compatible gateway in front of Azure, used verbatim), then the AZURE_OPENAI_ENDPOINT
        environment variable. The OPENAI_API_BASE environment variable is deliberately not consulted:
        it belongs to the "openai" class and would silently redirect Azure agents to whatever gateway
        that class uses.

        :param config: The fully specified llm config
        :return: The base URL, ending in "/openai/v1/" when derived from a resource endpoint
        :raises OpenAIError: When neither an endpoint nor an explicit base URL is configured
        """
        configured_endpoint: str = config.get("azure_endpoint")
        if configured_endpoint:
            return self.v1_base_url(configured_endpoint)

        base_url: str = config.get("openai_api_base")
        if base_url:
            return base_url

        # An empty string counts as "not configured": the neuro-san Dockerfiles export
        # AZURE_OPENAI_ENDPOINT="" so that the variable exists whether or not Azure is used.
        env_endpoint: str = os.getenv("AZURE_OPENAI_ENDPOINT")
        if env_endpoint:
            return self.v1_base_url(env_endpoint)

        raise self.create_config_error("Azure OpenAI needs an endpoint: set azure_endpoint in llm_config or the "
                                       "AZURE_OPENAI_ENDPOINT environment variable to the resource URL "
                                       "(https://<resource>.openai.azure.com), or set openai_api_base in "
                                       "llm_config to the full base URL of an OpenAI-compatible gateway.")

    def v1_base_url(self, azure_endpoint: str) -> str:
        """
        Turns a resource endpoint into the base URL of its v1 API.

        :param azure_endpoint: The resource URL, https://<resource>.openai.azure.com, with or without a
                trailing slash, surrounding whitespace, or the v1 path already appended
        :return: The endpoint with a single "/openai/v1/" appended
        """
        trimmed: str = azure_endpoint.strip().rstrip("/")
        # Tolerate an endpoint that already carries the v1 path, as Azure's own quickstarts show it.
        if trimmed.endswith(self.V1_PATH):
            return trimmed + "/"
        return trimmed + self.V1_PATH + "/"

    def resolve_credential(self, config: Dict[str, Any]) -> str:
        """
        Works out the credential to send as the Bearer token.

        Azure's v1 API accepts an API key in the Authorization: Bearer header (the header the OpenAI
        SDK always sends) as well as in the Azure-specific api-key header, and a Microsoft Entra
        access token in the Bearer header only. A configured Entra token wins over an API key.

        :param config: The fully specified llm config
        :return: The Entra token or API key to send
        :raises OpenAIError: When no credential is configured
        """
        # AD here means "ActiveDirectory", the former name of Microsoft Entra ID.
        azure_ad_token: str = self.get_value_or_env(config, "azure_ad_token", "AZURE_OPENAI_AD_TOKEN")
        if azure_ad_token:
            return azure_ad_token

        api_key: str = self.get_value_or_env(config, "openai_api_key", "AZURE_OPENAI_API_KEY")
        if api_key:
            return api_key

        # OPENAI_API_KEY is the documented last fallback (see the azure-openai class in default_llm_info.hocon).
        fallback_key: str = self.get_value_or_env(config, "openai_api_key", "OPENAI_API_KEY")
        if fallback_key:
            return fallback_key

        raise self.create_config_error("Azure OpenAI needs a credential: set openai_api_key in llm_config or the "
                                       "AZURE_OPENAI_API_KEY environment variable (OPENAI_API_KEY is used as a "
                                       "fallback), or azure_ad_token in llm_config or the AZURE_OPENAI_AD_TOKEN "
                                       "environment variable for a Microsoft Entra access token.")

    def resolve_deployment_name(self, config: Dict[str, Any], model_name: Optional[str]) -> str:
        """
        Works out the Azure deployment name to put in the "model" field of each request.

        :param config: The fully specified llm config
        :param model_name: The model id the llm_info resolution produced, if any (an alias such as
                "gpt-4o" has already become its snapshot "gpt-4o-2024-08-06" by now)
        :return: deployment_name from llm_config, else AZURE_OPENAI_DEPLOYMENT_NAME from the
                environment, else that model id
        :raises OpenAIError: When none of the three is available
        """
        deployment_name: str = self.get_value_or_env(config, "deployment_name", "AZURE_OPENAI_DEPLOYMENT_NAME")
        if deployment_name:
            return deployment_name

        # The azure-* entries in default_llm_info.hocon resolve to an OpenAI snapshot name such as
        # gpt-4o-2024-08-06, which is rarely what a deployment is called, so this fallback mostly
        # serves llm_configs that name the deployment directly as their model_name.
        if model_name:
            return model_name

        raise self.create_config_error("Azure OpenAI needs a deployment to call: set deployment_name in "
                                       "llm_config or the AZURE_OPENAI_DEPLOYMENT_NAME environment variable, "
                                       "or give a model_name that resolves to the name of the deployment.")

    def create_config_error(self, message: str) -> Exception:
        """
        Builds the exception for a missing endpoint, credential or deployment.

        openai.OpenAIError is the family the OpenAI SDK itself raises when a client cannot be configured
        (for instance a missing api_key), and the one DefaultLlmFactory catches at construction time to
        turn into the friendly API-key guidance of ApiKeyErrorCheck. A plain ValueError would bypass that
        guidance. The class is resolved lazily like the rest of the openai package in the policies.

        :param message: The error text; it names the llm_config key and environment variable involved so
                the guidance table in ApiKeyErrorCheck matches it
        :return: The exception to raise
        """
        # pylint: disable=invalid-name
        OpenAIError = self.resolver.resolve_class_in_module("OpenAIError",
                                                            module_name="openai",
                                                            install_if_missing="langchain-openai")
        return OpenAIError(message)

    def build_default_headers(self, config: Dict[str, Any]) -> Dict[str, str]:
        """
        Builds the default headers for the SDK client.

        :param config: The fully specified llm config
        :return: A new dictionary with any default_headers from llm_config plus the User-Agent that
                langchain's Azure integration sends, kept so that Azure-side telemetry sees no change
        """
        default_headers: Dict[str, str] = {}
        configured: Dict[str, str] = config.get("default_headers")
        if configured:
            # Copy rather than update in place: the config dict is shared with the caller.
            default_headers.update(configured)
        default_headers["User-Agent"] = "langchain-partner-python-azure-openai"
        return default_headers

    def warn_about_legacy_keys(self, config: Dict[str, Any]) -> None:
        """
        Logs a one-time warning when the llm_config carries keys of the dated Azure API.

        openai_api_version, openai_api_type and model_version selected and described the dated
        api-version routes that the v1 API replaced. They are ignored now; without a warning a
        config that still sets them would look like it works differently than it does.

        :param config: The fully specified llm config
        """
        legacy_present: List[str] = []
        for key in self.LEGACY_KEYS:
            # null and "" are the neutral values the class defaults carry; only a real value counts.
            if config.get(key):
                legacy_present.append(key)

        if not legacy_present or AzureLlmPolicy.legacy_keys_warned:
            return

        AzureLlmPolicy.legacy_keys_warned = True
        self.logger.warning("Ignoring llm_config key(s) %s: AzureLlmPolicy sends requests to Azure OpenAI's "
                            "v1 API, which takes no api-version. Remove them from the llm_config; "
                            "the OPENAI_API_VERSION environment variable is no longer read either.",
                            ", ".join(legacy_present))
