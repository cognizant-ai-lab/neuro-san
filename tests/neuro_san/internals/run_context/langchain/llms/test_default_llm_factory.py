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


class TestDefaultLlmFactory(TestCase):
    """
    Test cases for DefaultLlmFactory.create_full_llm_config() and the alias resolution behind it.

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
