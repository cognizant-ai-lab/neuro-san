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
import tempfile

from typing import Any
from typing import Dict
from typing import Set
from unittest import TestCase
from unittest.mock import patch

from typing_extensions import override

from neuro_san.internals.run_context.langchain.llms.default_llm_factory import DefaultLlmFactory


# The class-and-alias matrix plus get_chat_class_name() legitimately need more than 20 cases.
# pylint: disable=too-many-public-methods
class TestDefaultLlmFactory(TestCase):
    """
    Test cases for DefaultLlmFactory.create_full_llm_config() and the alias resolution behind it,
    and for get_chat_class_name(), which answers the class question without building a config.

    The focus is how "use_model_name" aliases in llm_info are followed, with and without a
    "class" key in the llm_config. See https://github.com/cognizant-ai-lab/neuro-san/issues/1298.

    Nothing here builds a chat model or makes a network call: only the fully specified config
    that create_full_llm_config() produces is inspected. Expected alias targets are read from
    the loaded llm_info rather than hard-coded, so the tests keep passing when an alias is
    moved to a newer model version.
    """

    # A one-key alias whose target is a full entry without a "use_model_name" of its own.
    ANTHROPIC_ALIAS: str = "claude-fable"

    # A one-key alias whose target is a dated OpenAI snapshot.
    OPENAI_ALIAS: str = "gpt-4o"

    # A full entry (class + use_model_name + model_info_url) that redirects to another entry.
    AZURE_REDIRECT: str = "azure-gpt-4o"

    # A name that will never be in llm_info.
    UNKNOWN_MODEL: str = "model-neuro-san-has-never-heard-of"

    # A user-defined alias pointing at a name that has no entry of its own.
    DANGLING_ALIAS: str = "my-claude"
    DANGLING_TARGET: str = "claude-not-yet-released"

    @override
    def setUp(self) -> None:
        """
        Pins the environment and loads the stock default_llm_info.hocon.

        AGENT_LLM_INFO_FILE is removed so that a deployer override present in the environment
        cannot change the alias table these tests check. OPENAI_API_KEY is pinned to a dummy so
        that nothing built here can see a real provider key.
        """
        # patch.dict with clear=False can only override variables, not delete them, so removing
        # AGENT_LLM_INFO_FILE needs a full copy handed to patch.dict with clear=True.
        environment: Dict[str, str] = {}
        for name, value in os.environ.items():
            if name != "AGENT_LLM_INFO_FILE":
                environment[name] = value
        environment["OPENAI_API_KEY"] = "sk-test"

        env_patcher: Any = patch.dict(os.environ, environment, clear=True)
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

        # Loaded after the environment is pinned so the stock hocon is what gets read.
        self.factory: DefaultLlmFactory = DefaultLlmFactory()
        self.factory.load()

    def _load_factory_with_extra_llm_info(self, extra_hocon: str) -> DefaultLlmFactory:
        """
        Builds a second factory whose llm_info is the stock file overlaid with the given hocon text.

        :param extra_hocon: The contents of a user llm_info_file to overlay on the defaults
        :return: A loaded DefaultLlmFactory using that overlay
        """
        # delete=False because the restorer opens the file by path after this handle is closed.
        # The cleanup removes it even if the test fails.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".hocon", delete=False) as hocon_file:
            hocon_file.write(extra_hocon)
            hocon_path: str = hocon_file.name
        self.addCleanup(os.remove, hocon_path)

        factory: DefaultLlmFactory = DefaultLlmFactory({"llm_info_file": hocon_path})
        factory.load()
        return factory

    def _dangling_alias_hocon(self) -> str:
        """
        Builds llm_info hocon text defining a one-key alias whose target has no entry.

        :return: The hocon text
        """
        return f"""
        {{
            "{self.DANGLING_ALIAS}": {{
                "use_model_name": "{self.DANGLING_TARGET}"
            }}
        }}
        """

    def _alias_target(self, alias: str) -> str:
        """
        Reads where an alias in the loaded llm_info points.

        :param alias: The alias entry name
        :return: The value of that entry's "use_model_name"
        """
        return self.factory.llm_infos[alias]["use_model_name"]

    # ---- "class" given: one of our classes -------------------------------------------------

    def test_class_with_alias_resolves_model_name(self) -> None:
        """
        With one of our classes, an alias model_name is replaced by the model id it points at.
        """
        config: Dict[str, Any] = {"class": "anthropic", "model_name": self.ANTHROPIC_ALIAS}

        full_config: Dict[str, Any] = self.factory.create_full_llm_config(config, None)

        self.assertEqual(self._alias_target(self.ANTHROPIC_ALIAS), full_config["model_name"])
        self.assertEqual("anthropic", full_config["class"])

    def test_class_with_alias_keeps_user_class(self) -> None:
        """
        The user's class is what gets used even when the alias target belongs to another class.
        """
        config: Dict[str, Any] = {"class": "anthropic-bedrock", "model_name": self.ANTHROPIC_ALIAS}

        full_config: Dict[str, Any] = self.factory.create_full_llm_config(config, None)

        self.assertEqual(self._alias_target(self.ANTHROPIC_ALIAS), full_config["model_name"])
        self.assertEqual("anthropic-bedrock", full_config["class"])

    def test_class_with_full_model_name_is_unchanged(self) -> None:
        """
        A model_name that already is the concrete model id stays as it is.
        """
        target: str = self._alias_target(self.ANTHROPIC_ALIAS)
        config: Dict[str, Any] = {"class": "anthropic", "model_name": target}

        full_config: Dict[str, Any] = self.factory.create_full_llm_config(config, None)

        self.assertEqual(target, full_config["model_name"])

    def test_class_with_unknown_model_name_passes_through(self) -> None:
        """
        A model_name llm_info has never heard of is passed through untouched, with no error.
        This is the original reason the "class" key exists.
        """
        config: Dict[str, Any] = {"class": "anthropic", "model_name": self.UNKNOWN_MODEL}

        full_config: Dict[str, Any] = self.factory.create_full_llm_config(config, None)

        self.assertEqual(self.UNKNOWN_MODEL, full_config["model_name"])
        self.assertEqual("anthropic", full_config["class"])

    def test_class_without_model_name_is_tolerated(self) -> None:
        """
        A class-only config (e.g. Azure selecting by deployment_name) neither fails nor gains a model_name.
        """
        config: Dict[str, Any] = {"class": "azure-openai", "deployment_name": "my-deployment"}

        full_config: Dict[str, Any] = self.factory.create_full_llm_config(config, None)

        self.assertIsNone(full_config.get("model_name"))
        self.assertEqual("my-deployment", full_config["deployment_name"])

    def test_class_with_redirect_entry_resolves_model_name(self) -> None:
        """
        A full entry that carries its own "use_model_name" (the azure-* shape) resolves to that name
        while the user's class is kept.
        """
        config: Dict[str, Any] = {"class": "azure-openai", "model_name": self.AZURE_REDIRECT}

        full_config: Dict[str, Any] = self.factory.create_full_llm_config(config, None)

        self.assertEqual(self._alias_target(self.AZURE_REDIRECT), full_config["model_name"])
        self.assertEqual("azure-openai", full_config["class"])

    def test_class_with_openai_alias_resolves_dated_model(self) -> None:
        """
        An OpenAI alias resolves to the dated snapshot, the same as it does without a class.
        """
        config: Dict[str, Any] = {"class": "openai", "model_name": self.OPENAI_ALIAS}

        full_config: Dict[str, Any] = self.factory.create_full_llm_config(config, None)

        self.assertEqual(self._alias_target(self.OPENAI_ALIAS), full_config["model_name"])

    def test_class_with_missing_sly_data_key_still_reports_it(self) -> None:
        """
        Alias resolution does not get in the way of reporting missing sly_data keys as a set.
        """
        config: Dict[str, Any] = {
            "class": "openai",
            "model_name": self.OPENAI_ALIAS,
            "openai_api_key": "sly_data",
        }

        result: Dict[str, Any] | Set[str] = self.factory.create_full_llm_config(config, None)

        self.assertIsInstance(result, set)
        self.assertEqual({"openai_api_key"}, result)

    def test_class_with_dangling_alias_passes_target_through(self) -> None:
        """
        With a class, an alias whose target has no entry resolves to the target name
        and is left for the provider to judge, instead of failing.
        """
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(self._dangling_alias_hocon())
        config: Dict[str, Any] = {"class": "anthropic", "model_name": self.DANGLING_ALIAS}

        full_config: Dict[str, Any] = factory.create_full_llm_config(config, None)

        self.assertEqual(self.DANGLING_TARGET, full_config["model_name"])

    # ---- "class" given: full langchain class path ----------------------------------------------

    def test_langchain_class_path_leaves_alias_alone(self) -> None:
        """
        With a full python class path, nothing from llm_info applies, so the alias stays literal.
        """
        config: Dict[str, Any] = {"class": "langchain_anthropic.ChatAnthropic", "model_name": self.ANTHROPIC_ALIAS}

        full_config: Dict[str, Any] = self.factory.create_full_llm_config(config, None)

        self.assertEqual(self.ANTHROPIC_ALIAS, full_config["model_name"])
        self.assertEqual("langchain_anthropic.ChatAnthropic", full_config["class"])

    def test_is_llm_info_class(self) -> None:
        """
        Only names from the llm_info "classes" table count as our classes.
        """
        self.assertTrue(self.factory.is_llm_info_class("anthropic"))
        self.assertTrue(self.factory.is_llm_info_class("azure-openai"))
        self.assertFalse(self.factory.is_llm_info_class("langchain_anthropic.ChatAnthropic"))
        self.assertFalse(self.factory.is_llm_info_class(self.UNKNOWN_MODEL))

    # ---- No "class": the long-standing path must not change --------------------------------------

    def test_no_class_with_alias_still_resolves(self) -> None:
        """
        Without a class, the alias still resolves and the class and max_tokens come from the target entry.
        """
        target: str = self._alias_target(self.ANTHROPIC_ALIAS)
        target_entry: Dict[str, Any] = self.factory.llm_infos[target]
        config: Dict[str, Any] = {"model_name": self.ANTHROPIC_ALIAS}

        full_config: Dict[str, Any] = self.factory.create_full_llm_config(config, None)

        self.assertEqual(target, full_config["model_name"])
        self.assertEqual(target_entry["class"], full_config["class"])
        # default_config has prompt_token_fraction 1.0, so max_tokens is the entry's max_output_tokens.
        self.assertEqual(target_entry["max_output_tokens"], full_config["max_tokens"])

    def test_no_class_with_redirect_entry_keeps_target_max_tokens(self) -> None:
        """
        A redirect entry keeps its own class but takes max_tokens from the entry it points at,
        because get_max_prompt_tokens() looks up the already-rewritten model_name.
        """
        target: str = self._alias_target(self.AZURE_REDIRECT)
        config: Dict[str, Any] = {"model_name": self.AZURE_REDIRECT}

        full_config: Dict[str, Any] = self.factory.create_full_llm_config(config, None)

        self.assertEqual(target, full_config["model_name"])
        self.assertEqual("azure-openai", full_config["class"])
        self.assertEqual(self.factory.llm_infos[target]["max_output_tokens"], full_config["max_tokens"])

    def test_no_class_with_unknown_model_name_raises(self) -> None:
        """
        Without a class there is nothing to instantiate for an unknown model, so it is an error.
        """
        config: Dict[str, Any] = {"model_name": self.UNKNOWN_MODEL}

        with self.assertRaises(ValueError) as context:
            self.factory.create_full_llm_config(config, None)

        self.assertIn(f"No llm entry for model_name {self.UNKNOWN_MODEL}", str(context.exception))

    def test_no_class_with_dangling_alias_raises(self) -> None:
        """
        Without a class, an alias whose target has no entry is still an error, as before.
        """
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(self._dangling_alias_hocon())
        config: Dict[str, Any] = {"model_name": self.DANGLING_ALIAS}

        with self.assertRaises(ValueError) as context:
            factory.create_full_llm_config(config, None)

        self.assertIn(f"No llm entry for use_model_name {self.DANGLING_TARGET}", str(context.exception))

    def test_no_class_two_key_alias_still_hops(self) -> None:
        """
        A sparse user overlay that adds a second key to a one-key alias keeps it behaving as an alias.
        """
        extra_hocon: str = f"""
        {{
            "{self.ANTHROPIC_ALIAS}": {{
                "model_info_url": "https://example.com/claude"
            }}
        }}
        """
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(extra_hocon)
        target: str = self._alias_target(self.ANTHROPIC_ALIAS)
        config: Dict[str, Any] = {"model_name": self.ANTHROPIC_ALIAS}

        full_config: Dict[str, Any] = factory.create_full_llm_config(config, None)

        self.assertEqual(target, full_config["model_name"])
        self.assertEqual(self.factory.llm_infos[target]["class"], full_config["class"])

    def test_get_max_prompt_tokens_with_dangling_alias_raises_value_error(self) -> None:
        """
        get_max_prompt_tokens() reports a dangling alias as a ValueError rather than tripping over None.
        """
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(self._dangling_alias_hocon())
        config: Dict[str, Any] = {"model_name": self.DANGLING_ALIAS, "prompt_token_fraction": 1.0}

        with self.assertRaises(ValueError) as context:
            factory.get_max_prompt_tokens(config)

        self.assertIn(f"No llm entry for use_model_name {self.DANGLING_TARGET}", str(context.exception))

    # ---- The resolution helpers on their own -----------------------------------------------------

    def test_resolve_model_name_alias_unknown_name_is_unchanged(self) -> None:
        """
        resolve_model_name_alias() hands back a name llm_info does not know, unchanged.
        """
        self.assertEqual(self.UNKNOWN_MODEL, self.factory.resolve_model_name_alias(self.UNKNOWN_MODEL))

    # ---- get_chat_class_name(): the class without building anything ------------------------------

    def test_get_chat_class_name_explicit_short_class(self) -> None:
        """
        An explicit llm_info class is returned as given, whatever the model_name says.
        """
        config: Dict[str, Any] = {"class": "anthropic", "model_name": self.OPENAI_ALIAS}

        self.assertEqual("anthropic", self.factory.get_chat_class_name(config))

    def test_get_chat_class_name_explicit_dotted_class(self) -> None:
        """
        A dotted user class path is returned as given, since nothing from llm_info applies to it.
        """
        config: Dict[str, Any] = {"class": "langchain_anthropic.ChatAnthropic", "model_name": self.ANTHROPIC_ALIAS}

        self.assertEqual("langchain_anthropic.ChatAnthropic", self.factory.get_chat_class_name(config))

    def test_get_chat_class_name_from_model_name(self) -> None:
        """
        Without a class, the class comes from the llm_info entry for the model_name.
        """
        config: Dict[str, Any] = {"model_name": "gemini-2.5-flash"}

        self.assertEqual("gemini", self.factory.get_chat_class_name(config))

    def test_get_chat_class_name_follows_alias(self) -> None:
        """
        A one-key alias is followed to the entry that carries the class.
        """
        config: Dict[str, Any] = {"model_name": self.OPENAI_ALIAS}

        self.assertEqual("openai", self.factory.get_chat_class_name(config))

    def test_get_chat_class_name_unknown_model_is_none(self) -> None:
        """
        An unknown model_name yields None rather than an error, unlike create_full_llm_config().
        """
        config: Dict[str, Any] = {"model_name": self.UNKNOWN_MODEL}

        self.assertIsNone(self.factory.get_chat_class_name(config))

    def test_get_chat_class_name_without_model_name_uses_default_config(self) -> None:
        """
        Without a model_name, default_config's model_name decides, the same as create_full_llm_config().
        """
        default_config: Dict[str, Any] = self.factory.llm_infos.get("default_config")
        default_model_name: str = default_config.get("model_name")
        expected: str = self.factory.get_chat_class_name({"model_name": default_model_name})
        # The default model must resolve to something, or this test would pass vacuously.
        self.assertIsNotNone(expected)

        self.assertEqual(expected, self.factory.get_chat_class_name({}))

    def test_get_chat_class_name_non_dict_entry_is_none(self) -> None:
        """
        A user llm_info entry that is not a dictionary yields None instead of an AttributeError.
        """
        extra_hocon: str = '{ "gemini-2.5-flash": "just a string" }'
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(extra_hocon)

        self.assertIsNone(factory.get_chat_class_name({"model_name": "gemini-2.5-flash"}))

    def test_get_chat_class_name_alias_to_non_dict_entry_is_none(self) -> None:
        """
        An alias whose target entry is not a dictionary yields None as well.
        """
        extra_hocon: str = """
        {
            "weird": {
                "use_model_name": "target"
            },
            "target": "just a string"
        }
        """
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(extra_hocon)

        self.assertIsNone(factory.get_chat_class_name({"model_name": "weird"}))

    def test_get_chat_class_name_unhashable_alias_target_is_none(self) -> None:
        """
        An alias whose "use_model_name" is a list yields None instead of a TypeError.
        """
        extra_hocon: str = """
        {
            "weird": {
                "use_model_name": ["gemini-2.5-flash"]
            }
        }
        """
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(extra_hocon)

        self.assertIsNone(factory.get_chat_class_name({"model_name": "weird"}))

    def test_get_chat_class_name_null_alias_keeps_own_class(self) -> None:
        """
        A null "use_model_name" is not an alias, so the entry's own class is returned.
        """
        extra_hocon: str = '{ "my-gemini": { "class": "gemini", "use_model_name": null } }'
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(extra_hocon)

        self.assertEqual("gemini", factory.get_chat_class_name({"model_name": "my-gemini"}))

    def test_get_chat_class_name_non_dict_default_config_is_none(self) -> None:
        """
        A default_config that is not a dictionary yields None for a config without model_name.
        """
        extra_hocon: str = '{ "default_config": "just a string" }'
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(extra_hocon)

        self.assertIsNone(factory.get_chat_class_name({}))

    # ---- get_llm_info_file(): which user file, if any, is read on top of the stock one ----------

    def test_get_llm_info_file_stock_is_none(self) -> None:
        """
        With no llm_info_file in the config and no AGENT_LLM_INFO_FILE in the environment, there is none.
        """
        self.assertIsNone(self.factory.get_llm_info_file())

    def test_get_llm_info_file_from_config(self) -> None:
        """
        The config's llm_info_file is reported as given; the constructor does not read it.
        """
        factory: DefaultLlmFactory = DefaultLlmFactory({"llm_info_file": "/no/such/llm_info.hocon"})

        self.assertEqual("/no/such/llm_info.hocon", factory.get_llm_info_file())

    # ---- get_chat_class_family(): the root class behind "extends" --------------------------------

    def _user_class_hocon(self, with_marker: bool) -> str:
        """
        Builds llm_info hocon text defining a user class that extends openai, with or without
        the provider_tools marker in its own args.

        :param with_marker: True to declare "provider_tools" in the class's own args
        :return: The hocon text
        """
        marker: str = ""
        if with_marker:
            marker = '"provider_tools": null,'
        return f"""
        {{
            "classes": {{
                "my-openai": {{
                    "extends": "openai",
                    "args": {{
                        {marker}
                        "openai_api_base": "http://localhost:1234/v1"
                    }}
                }}
            }}
        }}
        """

    def test_get_chat_class_family_root_class_is_itself(self) -> None:
        """
        A class with no "extends" is its own family.
        """
        self.assertEqual("openai", self.factory.get_chat_class_family("openai"))

    def test_get_chat_class_family_azure_openai_is_openai(self) -> None:
        """
        azure-openai extends openai, so its family is openai.
        """
        self.assertEqual("openai", self.factory.get_chat_class_family("azure-openai"))

    def test_get_chat_class_family_anthropic_bedrock_is_anthropic(self) -> None:
        """
        anthropic-bedrock extends anthropic, so its family is anthropic.
        """
        self.assertEqual("anthropic", self.factory.get_chat_class_family("anthropic-bedrock"))

    def test_get_chat_class_family_is_case_insensitive(self) -> None:
        """
        "Gemini" is looked up lowercased, the way the runtime looks up its policy.
        """
        self.assertEqual("gemini", self.factory.get_chat_class_family("Gemini"))

    def test_get_chat_class_family_unknown_is_none(self) -> None:
        """
        A class that is not in the classes table, or no class at all, has no family.
        """
        self.assertIsNone(self.factory.get_chat_class_family("no-such-class"))
        self.assertIsNone(self.factory.get_chat_class_family(None))

    def test_get_chat_class_family_dotted_class_is_none(self) -> None:
        """
        The python path of a langchain chat model class is not in the table, so it has no family.
        """
        self.assertIsNone(self.factory.get_chat_class_family("langchain_openai.chat_models.base.ChatOpenAI"))

    def test_get_chat_class_family_dangling_extends_stops_at_last_known_class(self) -> None:
        """
        A class whose "extends" names nothing in the table is reported as its own family.
        """
        extra_hocon: str = '{ "classes": { "orphan": { "extends": "no-such-class", "args": {} } } }'
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(extra_hocon)

        self.assertEqual("orphan", factory.get_chat_class_family("orphan"))

    def test_get_chat_class_family_cycle_ends(self) -> None:
        """
        Two classes extending each other end the walk at one of them instead of looping forever.
        """
        extra_hocon: str = """
        {
            "classes": {
                "cycle-a": { "extends": "cycle-b", "args": {} },
                "cycle-b": { "extends": "cycle-a", "args": {} }
            }
        }
        """
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(extra_hocon)

        self.assertIn(factory.get_chat_class_family("cycle-a"), ["cycle-a", "cycle-b"])

    # ---- declares_provider_tools(): the class's own args, not its parent's -----------------------

    def test_declares_provider_tools_stock_supported_classes(self) -> None:
        """
        The stock openai, azure-openai, anthropic and gemini classes declare provider_tools in their own args.
        """
        for class_name in ["openai", "azure-openai", "anthropic", "gemini"]:
            self.assertTrue(self.factory.declares_provider_tools(class_name), class_name)

    def test_declares_provider_tools_stock_unsupported_classes(self) -> None:
        """
        Classes that only inherit the key through "extends", or never had it, do not declare it.
        """
        for class_name in ["anthropic-bedrock", "ollama"]:
            self.assertFalse(self.factory.declares_provider_tools(class_name), class_name)

    def test_get_default_arg_value_from_class_of_model_name(self) -> None:
        """
        With only a model_name, the default comes from the resolved class's args.
        """
        self.assertIs(True, self.factory.get_default_arg_value({"model_name": "gpt-4.1"}, "use_responses_api"))

    def test_get_default_arg_value_with_class_follows_extends(self) -> None:
        """
        With a "class" in the llm_config, only that class's args (merged through extends) supply the default.
        """
        config: Dict[str, Any] = {"class": "azure-openai", "model_name": "gpt-5.2", "deployment_name": "d"}
        self.assertIs(True, self.factory.get_default_arg_value(config, "use_responses_api"))

    def test_get_default_arg_value_honours_user_class_default(self) -> None:
        """
        A user llm_info that changes a class default is what the runtime would fill in.
        """
        extra_hocon: str = '{ "classes": { "openai": { "args": { "use_responses_api": false } } } }'
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(extra_hocon)

        self.assertIs(False, factory.get_default_arg_value({"model_name": "gpt-4.1"}, "use_responses_api"))
        self.assertIs(False, factory.get_default_arg_value({"class": "azure-openai"}, "use_responses_api"))

    def test_get_default_arg_value_unknown_is_none(self) -> None:
        """
        An unknown model or class, or a key no class sets, yields None without raising.
        """
        self.assertIsNone(self.factory.get_default_arg_value({"model_name": "no-such-model"}, "use_responses_api"))
        self.assertIsNone(self.factory.get_default_arg_value({"class": "my.pkg.MyChat"}, "use_responses_api"))
        self.assertIsNone(self.factory.get_default_arg_value({"model_name": "gpt-4.1"}, "no_such_key"))

    def test_declares_provider_tools_unknown_is_false(self) -> None:
        """
        A class that is not in the table, or no class at all, declares nothing.
        """
        self.assertFalse(self.factory.declares_provider_tools("no-such-class"))
        self.assertFalse(self.factory.declares_provider_tools(None))

    def test_declares_provider_tools_user_class_with_marker(self) -> None:
        """
        A user class extending openai that declares the key in its own args is supported.
        """
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(self._user_class_hocon(True))

        self.assertTrue(factory.declares_provider_tools("my-openai"))
        self.assertEqual("openai", factory.get_chat_class_family("my-openai"))

    def test_declares_provider_tools_user_class_without_marker(self) -> None:
        """
        A user class extending openai without the key in its own args is not supported, even
        though get_chat_class_args() would merge the parent's key in.
        """
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(self._user_class_hocon(False))

        self.assertFalse(factory.declares_provider_tools("my-openai"))
        self.assertEqual("openai", factory.get_chat_class_family("my-openai"))
        self.assertIn("provider_tools", factory.get_chat_class_args("my-openai"))

    def test_declares_provider_tools_string_class_entry_is_false(self) -> None:
        """
        A class entry that is not a dictionary declares nothing and is its own family, without raising.
        """
        extra_hocon: str = '{ "classes": { "stringy": "just a string" } }'
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(extra_hocon)

        self.assertFalse(factory.declares_provider_tools("stringy"))
        self.assertEqual("stringy", factory.get_chat_class_family("stringy"))

    def test_declares_provider_tools_non_dict_args_is_false(self) -> None:
        """
        A class whose "args" is not a dictionary declares nothing, while its "extends" still gives it a family.
        """
        extra_hocon: str = '{ "classes": { "no-args": { "extends": "openai", "args": "oops" } } }'
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(extra_hocon)

        self.assertFalse(factory.declares_provider_tools("no-args"))
        self.assertEqual("openai", factory.get_chat_class_family("no-args"))
