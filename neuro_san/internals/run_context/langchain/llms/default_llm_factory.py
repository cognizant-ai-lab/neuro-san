
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

from typing import Any
from typing import Dict
from typing import List
from typing import Type

import os

from google.auth.exceptions import DefaultCredentialsError
from openai import OpenAIError
from pydantic_core import ValidationError

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.language_models.base import BaseLanguageModel

from leaf_common.config.dictionary_overlay import DictionaryOverlay
from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.internals.interfaces.context_type_llm_factory import ContextTypeLlmFactory
from neuro_san.internals.run_context.langchain.llms.langchain_llm_factory import LangChainLlmFactory
from neuro_san.internals.run_context.langchain.llms.llm_info_restorer import LlmInfoRestorer
from neuro_san.internals.run_context.langchain.llms.standard_langchain_llm_factory import StandardLangChainLlmFactory
from neuro_san.internals.run_context.langchain.util.api_key_error_check import ApiKeyErrorCheck
from neuro_san.internals.run_context.langchain.util.argument_validator import ArgumentValidator
from neuro_san.internals.utils.resolver_util import ResolverUtil


class DefaultLlmFactory(ContextTypeLlmFactory, LangChainLlmFactory):
    """
    Factory class for LLM operations

    Most methods take a config dictionary which consists of the following keys:

        "model_name"                The name of the model.
                                    Default if not specified is "gpt-3.5-turbo"

        "temperature"               A float "temperature" value with which to
                                    initialize the chat model.  In general,
                                    higher temperatures yield more random results.
                                    Default if not specified is 0.7

        "prompt_token_fraction"     The fraction of total tokens (not necessarily words
                                    or letters) to use for a prompt. Each model_name
                                    has a documented number of max_tokens it can handle
                                    which is a total count of message + response tokens
                                    which goes into the calculation involved in
                                    get_max_prompt_tokens().
                                    By default the value is 0.5.

        "max_tokens"                The maximum number of tokens to use in
                                    get_max_prompt_tokens(). By default this comes from
                                    the model description in this class.
    """

    def __init__(self, config: Dict[str, Any] = None):
        """
        Constructor

        :param config: The config dictionary which may or may not contain
                       keys for the context_type and agent_llm_info_file
        """
        self.llm_infos: Dict[str, Any] = {}
        self.overlayer = DictionaryOverlay()
        self.llm_factories: List[LangChainLlmFactory] = [
            StandardLangChainLlmFactory()
        ]
        if config:
            self.llm_info_file: str = config.get("agent_llm_info_file")
        else:
            self.llm_info_file = None

    def load(self):
        """
        Loads the LLM information from hocon files.
        """
        restorer = LlmInfoRestorer()
        self.llm_infos = restorer.restore()

        # Mix in user-specified llm info, if available.
        # First check "agent_llm_info_file" key from agent network hocon.
        # If that is unavailable, fallback to env variable.
        llm_info_file: str = self.llm_info_file
        if not llm_info_file:
            llm_info_file = os.getenv("AGENT_LLM_INFO_FILE")
        if llm_info_file is not None and len(llm_info_file) > 0:
            extra_llm_infos: Dict[str, Any] = restorer.restore(file_reference=llm_info_file)
            self.llm_infos = self.overlayer.overlay(self.llm_infos, extra_llm_infos)

        # sanitize the llm_infos keys
        self.llm_infos = self.sanitize_keys(self.llm_infos)

        # Resolve any new llm factories
        extractor = DictionaryExtractor(self.llm_infos)
        llm_factory_classes: List[str] = []
        llm_factory_classes = extractor.get("classes.factories", llm_factory_classes)
        if not isinstance(llm_factory_classes, List):
            raise ValueError(f"The classes.factories key in {llm_info_file} must be a list of strings")

        for llm_factory_class_name in llm_factory_classes:
            llm_factory: LangChainLlmFactory = self.resolve_one_llm_factory(llm_factory_class_name, llm_info_file)
            # Success. Tack it on to the list
            self.llm_factories.append(llm_factory)

    def resolve_one_llm_factory(self, llm_factory_class_name: str, llm_info_file: str) -> LangChainLlmFactory:
        """
        :param llm_factory_class_name: A single class name to resolve.
        :param llm_info_file: The name of the hocon file with the class names, to reference
                        when exceptions are thrown.
        :return: A LangChainLlmFactory instance as per the input
        """
        if not isinstance(llm_factory_class_name, str):
            raise ValueError(f"The value for the classes.factories key in {llm_info_file} "
                             "must be a list of strings")

        # Resolve and instantiate the factory class
        llm_factory = ResolverUtil.create_instance(
            class_name=llm_factory_class_name,
            class_name_source=llm_info_file,
            type_of_class=LangChainLlmFactory
        )

        return llm_factory

    def create_llm(
            self,
            config: Dict[str, Any],
            callbacks: List[BaseCallbackHandler] = None
    ) -> BaseLanguageModel:
        """
        Creates a langchain LLM based on the 'model_name' value of
        the config passed in.

        :param config: A dictionary which describes which LLM to use.
                See the class comment for details.
        :param callbacks: A list of BaseCallbackHandlers to add to the chat model.
        :return: A BaseLanguageModel (can be Chat or LLM)
                Can raise a ValueError if the config's model_name value is
                unknown to this method.
        """
        full_config: Dict[str, Any] = self.create_full_llm_config(config)
        llm: BaseLanguageModel = self.create_base_chat_model(full_config, callbacks)
        return llm

    def create_full_llm_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        :param config: The llm_config from the user
        :return: The fully specified config with defaults filled in.
        """

        class_from_llm_config: str = config.get("class")
        if class_from_llm_config:
            if not isinstance(class_from_llm_config, str):
                raise ValueError("Value of 'class' has to be string.")
            # A "class" key in the config indicates the user has specified a particular LLM implementation.
            # However, the config may only contain partial arguments (e.g., {"arg_1": 0.5}) and omit others.
            #
            # In the standard factory, LLM classes are instantiated like:
            #   ChatOpenAI(arg_1=config.get("arg_1"), arg_2=config.get("arg_2"))
            # If a required argument like "arg_2" is missing in the config, config.get("arg_2") returns None,
            # which may raise an error during instantiation if the argument has no default.
            #
            # To prevent this, we first fetch the default arguments for the given class from llm_info,
            # then merge them with the user-provided config. This ensures all expected arguments are present,
            # and the user’s config values take precedence over the defaults.
            config_from_class_in_llm_info: Dict[str, Any] = self.get_chat_class_args(class_from_llm_config)

            # Merge the defaults from llm_info with the user-defined config,
            # giving priority to values in config.
            return self.overlayer.overlay(config_from_class_in_llm_info, config)

        default_config: Dict[str, Any] = self.llm_infos.get("default_config")
        use_config = self.overlayer.overlay(default_config, config)

        model_name = use_config.get("model_name")

        llm_entry = self.llm_infos.get(model_name)
        if llm_entry is None:
            raise ValueError(f"No llm entry for model_name {model_name}")

        # Get some bits from the llm_entry
        use_model_name = llm_entry.get("use_model_name", model_name)
        if len(llm_entry.keys()) <= 2 and use_model_name is not None:
            # We effectively have an alias. Switch out the llm entry.
            llm_entry = self.llm_infos.get(use_model_name)
            if llm_entry is None:
                raise ValueError(f"No llm entry for use_model_name {use_model_name} in {model_name}")

        # Take a look at the chat classes.
        chat_class_name: str = llm_entry.get("class")
        if chat_class_name is None:
            raise ValueError(f"llm info entry for {use_model_name} requires a 'class' key/value pair.")

        # Get defaults for the chat class
        chat_args: Dict[str, Any] = self.get_chat_class_args(chat_class_name, use_model_name)

        # Get a new sense of the default config now that we have the default args for the chat class.
        default_config = self.overlayer.overlay(chat_args, default_config)

        # Now that we have the true defaults, overlay the config that came in to get the
        # config we are going to use.
        full_config: Dict[str, Any] = self.overlayer.overlay(default_config, config)
        full_config["class"] = chat_class_name
        full_config["model_name"] = llm_entry.get("use_model_name", use_model_name)

        # Attempt to get a max_tokens through calculation
        full_config["max_tokens"] = self.get_max_prompt_tokens(full_config)

        return full_config

    def get_chat_class_args(self, chat_class_name: str, use_model_name: str = None) -> Dict[str, Any]:
        """
        :param chat_class_name: string name of the chat class to look up.
        :param use_model_name: the original model name that prompted the chat class lookups
        :return: A dictionary of default arguments for the chat class.
                Can throw an exception if the chat class does not exist.
        """

        # Find the chat class.
        chat_classes: Dict[str, Any] = self.llm_infos.get("classes")
        chat_class: Dict[str, Any] = chat_classes.get(chat_class_name)
        if chat_class is None:
            if use_model_name is not None:
                # If use_model_name is given, it must have a "class" in "classes"
                raise ValueError(f"llm info entry for {use_model_name} uses a 'class' of {chat_class_name} "
                                 "which is not defined in the 'classes' table.")
            # If use_model_name is not provided and chat_class_name is not in "classes" in llm_info,
            # it could be a user-specified langchain model class
            return {}

        # Get the args from the chat class
        args: Dict[str, Any] = chat_class.get("args")

        extends: str = chat_class.get("extends")
        if extends is not None:
            # If this class extends another, get its args too.
            extends_args: Dict[str, Any] = self.get_chat_class_args(extends, use_model_name)
            args = self.overlayer.overlay(args, extends_args)

        return args

    def create_base_chat_model(self, config: Dict[str, Any],
                               callbacks: List[BaseCallbackHandler] = None) -> BaseLanguageModel:
        """
        Create a BaseLanguageModel from the fully-specified llm config either from standard LLM factory,
        user-defined LLM factory, or user-specified langchain model class.
        :param config: The fully specified llm config which is a product of
                    _create_full_llm_config() above.
        :param callbacks: A list of BaseCallbackHandlers to add to the chat model.
        :return: A BaseLanguageModel (can be Chat or LLM)
                Can raise a ValueError if the config's class or model_name value is
                unknown to this method.
        """
        llm: BaseLanguageModel = None

        # Loop through the loaded factories in order until we can find one
        # that can create the llm.
        found_exception: Exception = None
        for llm_factory in self.llm_factories:
            try:
                llm = llm_factory.create_base_chat_model(config, callbacks)
                if llm is not None and isinstance(llm, BaseLanguageModel):
                    # We found what we were looking for
                    found_exception = None
                    break

            # Catch some common wrong or missing API key errors in a single place
            # with some verbose error messaging.
            except (DefaultCredentialsError, OpenAIError, ValidationError) as exception:
                # Will re-raise but with the right exception text it will
                # also provide some more helpful failure text.
                message: str = ApiKeyErrorCheck.check_for_api_key_exception(exception)
                if message is not None:
                    raise ValueError(message) from exception
                found_exception = exception

            except ValueError as exception:
                # Let the next model have a crack
                found_exception = exception

        # Try resolving via 'class' in config if factories failed
        class_path: str = config.get("class")
        if llm is None and found_exception is not None and class_path:
            llm = self.create_base_chat_model_from_user_class(class_path, config)
            found_exception = None

        if found_exception is not None:
            raise found_exception

        return llm

    def create_base_chat_model_from_user_class(
            self,
            class_path: str,
            config: Dict[str, Any],
            callbacks: List[BaseCallbackHandler] = None
    ) -> BaseLanguageModel:
        """
        Create a BaseLanguageModel from the user-specified langchain model class.
        :param class_path: A string in the form of <package>.<module>.<Class>
        :param config: The fully specified llm config which is a product of
                    _create_full_llm_config() above.
        :param callbacks: A list of BaseCallbackHandlers to add to the chat model.

        :return: A BaseLanguageModel
        """

        if not isinstance(class_path, str):
            raise ValueError("'class' in llm_config must be a string")

        # Resolve the 'class'
        llm_class: Type[BaseLanguageModel] = ResolverUtil.create_class(
            class_name=class_path,
            class_name_source="agent network hocon file",
            type_of_class=BaseLanguageModel
        )

        # Copy the config, take 'class' out, and add callbacks
        # Then unpack into llm constructor
        user_config: Dict[str, Any] = config.copy()
        user_config.pop("class")
        user_config["callbacks"] = callbacks

        # Check for invalid args and throw error if found
        ArgumentValidator.check_invalid_args(llm_class, user_config)

        return llm_class(**user_config)

    def get_max_prompt_tokens(self, config: Dict[str, Any]) -> int:
        """
        :param config: A dictionary which describes which LLM to use.
        :return: The maximum number of tokens given the 'model_name' in the
                config dictionary.
        """

        model_name = config.get("model_name")

        llm_entry = self.llm_infos.get(model_name)
        if llm_entry is None:
            raise ValueError(f"No llm entry for model_name {model_name}")

        use_model_name = llm_entry.get("use_model_name", model_name)
        if len(llm_entry.keys()) <= 2 and use_model_name is not None:
            # We effectively have an alias. Switch out the llm entry.
            llm_entry = self.llm_infos.get(use_model_name)

        entry_max_tokens = llm_entry.get("max_output_tokens")
        prompt_token_fraction = config.get("prompt_token_fraction")
        use_max_tokens = int(entry_max_tokens * prompt_token_fraction)

        # Allow the actual value for max_tokens to come from the config, if there
        max_prompt_tokens = config.get("max_tokens", use_max_tokens)
        if max_prompt_tokens is None:
            max_prompt_tokens = use_max_tokens

        return max_prompt_tokens

    def strip_outer_quotes(self, s: str) -> str:
        """
        :param s: The input string to sanitize.
        :return: The input string without surrounding multiple quotes, if they were present.
        Otherwise, returns the string unchanged.
        """
        if len(s) >= 2 and s[0] in ["'", '"']:
            quote_char = s[0]
            unquoted = s[1:-1]

            # Only strip quotes if inner value does not contain the same quote char
            # and does not start with whitespace
            if quote_char not in unquoted and not unquoted.startswith(" "):
                return unquoted
        return s

    def sanitize_keys(self, d: Dict[str, Any]) -> Dict[str, Any]:
        """
        Returns a new dictionary with surrounding double quotes stripped from all keys.
        This is typically used to clean up configuration dictionaries where key names may
        be quoted (e.g., '"llama3.1"' instead of "llama3.1") due to parsing artifacts.
        Only the top-level keys are sanitized; nested keys are left unchanged.
        :param d: The input dictionary with potentially quoted keys.
        :return: A new dictionary with the same values, but with sanitized keys.
        """
        return {self.strip_outer_quotes(k): v for k, v in d.items()}
