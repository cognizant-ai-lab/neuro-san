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
# One test class per source class is the repo convention, so the test count grows with the class.
# pylint: disable=too-many-public-methods

import asyncio
import os
import subprocess
import sys
import tempfile

from typing import Any
from typing import Dict
from typing import List
from typing import Set
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from typing_extensions import override

from neuro_san.internals.run_context.langchain.llms.default_llm_factory import DefaultLlmFactory
from neuro_san.internals.run_context.langchain.llms.langchain_llm_resources import LangChainLlmResources
from neuro_san.internals.run_context.langchain.llms.tool_strict_chat_openai import ToolStrictChatOpenAI


class TestDefaultLlmFactory(TestCase):
    """
    Test cases for DefaultLlmFactory.create_full_llm_config() and the alias resolution behind it.

    The focus is how "use_model_name" aliases in llm_info are followed, with and without a
    "class" key in the llm_config. See https://github.com/cognizant-ai-lab/neuro-san/issues/1298.
    The "extends" tests check that a class's own args win over the ones it inherits.

    Nothing here makes a network call. Most tests only inspect the fully specified config that
    create_full_llm_config() produces; the tool_strict tests also build the chat model to see the
    class default land on it. One test imports the factory module in a child interpreter with the
    openai packages blocked, to check that the openai chat model class loads only when a model is
    built. Expected alias targets are read from the loaded llm_info rather than hard-coded, so the
    tests keep passing when an alias is moved to a newer model version.
    """

    # Runs in a child interpreter. A None entry in sys.modules makes an import fail the way a missing
    # package does, so this imports the factory module with the openai packages blocked. The check
    # afterwards makes the script fail, rather than pass by accident, if either package got imported.
    IMPORT_WITHOUT_OPENAI_SCRIPT: str = """
import importlib
import sys

sys.modules["openai"] = None
sys.modules["langchain_openai"] = None
importlib.import_module("neuro_san.internals.run_context.langchain.llms.default_llm_factory")
if sys.modules.get("openai") is not None or sys.modules.get("langchain_openai") is not None:
    raise SystemExit("an openai package was imported")
print("FACTORY_IMPORTED_WITHOUT_OPENAI")
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

    # A Bedrock model id whose stock entry has "class": "anthropic-bedrock".
    BEDROCK_MODEL: str = "global.anthropic.claude-fable-5-1"

    # A sparse llm info file that gives "anthropic-bedrock" two defaults of its own.
    # The "anthropic" class it extends declares both keys as null.
    BEDROCK_CLASS_DEFAULTS_HOCON: str = """
{
    "classes": {
        "anthropic-bedrock": {
            "args": {
                "max_tokens": 64000,
                "temperature": 0.2
            }
        }
    }
}
"""

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

    # ---- "class" given: the strict default for OpenAI function tools --------------------------

    @staticmethod
    def _close_llm_resources(llm_resources: LangChainLlmResources) -> None:
        """
        Releases the web client a chat model built by the factory holds.

        :param llm_resources: The resources create_llm() returned
        """
        asyncio.run(llm_resources.close_of_work())

    def test_openai_classes_build_the_chat_model_with_tool_strict_false(self) -> None:
        """
        The hocon default reaches the chat model itself: a model built through the factory for the
        "openai" class, for "azure-openai" and for a bare OpenAI model name carries tool_strict False.
        """
        configs: List[Dict[str, Any]] = [
            {"class": "openai", "model_name": self.OPENAI_ALIAS},
            # The credential falls back to the pinned OPENAI_API_KEY; the endpoint never gets called.
            {"class": "azure-openai", "deployment_name": "my-deployment",
             "azure_endpoint": "https://unit-test.openai.azure.com"},
            {"model_name": self.OPENAI_ALIAS},
        ]
        for config in configs:
            # The label is a string so that the subtest stays picklable under xdist.
            with self.subTest(config=str(config)):
                llm_resources: LangChainLlmResources = self.factory.create_llm(config, None)
                self.addCleanup(self._close_llm_resources, llm_resources)

                llm: Any = llm_resources.get_model()
                self.assertIsInstance(llm, ToolStrictChatOpenAI)
                self.assertIs(llm.tool_strict, False)

    def test_openai_classes_default_tool_strict_to_false(self) -> None:
        """
        The "openai" class defaults tool_strict to false, and "azure-openai" inherits that default.
        """
        openai_config: Dict[str, Any] = {"class": "openai", "model_name": self.OPENAI_ALIAS}
        azure_config: Dict[str, Any] = {"class": "azure-openai", "deployment_name": "my-deployment"}

        openai_full_config: Dict[str, Any] = self.factory.create_full_llm_config(openai_config, None)
        azure_full_config: Dict[str, Any] = self.factory.create_full_llm_config(azure_config, None)

        self.assertIs(openai_full_config.get("tool_strict"), False)
        self.assertIs(azure_full_config.get("tool_strict"), False)

    def test_tool_strict_null_in_llm_config_survives_the_overlay(self) -> None:
        """
        An agent that sets "tool_strict": null gets None in its full config, not the class default of
        false, so the chat model sends no strict value at all for it.
        """
        config: Dict[str, Any] = {"class": "openai", "model_name": self.OPENAI_ALIAS}
        null_config: Dict[str, Any] = dict(config)
        null_config["tool_strict"] = None

        # The baseline shows there is a non-null default for the null to override.
        self.assertIs(self.factory.create_full_llm_config(config, None).get("tool_strict"), False)
        full_config: Dict[str, Any] = self.factory.create_full_llm_config(null_config, None)

        self.assertIn("tool_strict", full_config)
        self.assertIsNone(full_config.get("tool_strict"))

    def test_tool_strict_null_in_a_sparse_llm_info_file_overrides_the_default(self) -> None:
        """
        A sparse llm info file that deep-merges over the default can set the class default to null, the
        server-wide override the reference documents for the "openai" class arguments.
        """
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(
            '{ "classes": { "openai": { "args": { "tool_strict": null } } } }')
        config: Dict[str, Any] = {"class": "openai", "model_name": self.OPENAI_ALIAS}

        # The stock factory gives the default, so the None below really comes from the sparse file.
        self.assertIs(self.factory.create_full_llm_config(config, None).get("tool_strict"), False)
        full_config: Dict[str, Any] = factory.create_full_llm_config(config, None)

        self.assertIn("tool_strict", full_config)
        self.assertIsNone(full_config.get("tool_strict"))

    # ---- "extends": a class's own args win over the ones it inherits ----------------------------

    def test_extending_class_args_override_the_parent(self) -> None:
        """
        Defaults that a sparse llm info file gives "anthropic-bedrock" win over the nulls that the
        "anthropic" class it extends declares for the same keys.
        """
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(
            TestDefaultLlmFactory.BEDROCK_CLASS_DEFAULTS_HOCON)

        args: Dict[str, Any] = factory.get_chat_class_args("anthropic-bedrock")

        self.assertEqual(64000, args.get("max_tokens"))
        self.assertEqual(0.2, args.get("temperature"))
        # The parent class keeps its own nulls.
        self.assertIsNone(factory.get_chat_class_args("anthropic").get("max_tokens"))

    def test_extending_class_default_reaches_an_llm_config_that_names_the_class(self) -> None:
        """
        An llm_config that names "anthropic-bedrock" gets the class defaults from a sparse llm info
        file, and a "max_tokens" of its own still wins over the default.
        """
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(
            TestDefaultLlmFactory.BEDROCK_CLASS_DEFAULTS_HOCON)
        config: Dict[str, Any] = {
            "class": "anthropic-bedrock",
            "model_name": TestDefaultLlmFactory.BEDROCK_MODEL,
        }
        own_config: Dict[str, Any] = dict(config)
        own_config["max_tokens"] = 32000

        full_config: Dict[str, Any] = factory.create_full_llm_config(config, None)
        own_full_config: Dict[str, Any] = factory.create_full_llm_config(own_config, None)

        self.assertEqual(64000, full_config.get("max_tokens"))
        self.assertEqual(0.2, full_config.get("temperature"))
        self.assertEqual(32000, own_full_config.get("max_tokens"))

    def test_extending_class_default_reaches_an_llm_config_without_class(self) -> None:
        """
        Without "class", the model's entry selects "anthropic-bedrock" and the class defaults apply,
        except "max_tokens", which still comes from the entry's max_output_tokens.
        """
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(
            TestDefaultLlmFactory.BEDROCK_CLASS_DEFAULTS_HOCON)
        config: Dict[str, Any] = {"model_name": TestDefaultLlmFactory.BEDROCK_MODEL}

        full_config: Dict[str, Any] = factory.create_full_llm_config(config, None)
        stock_full_config: Dict[str, Any] = self.factory.create_full_llm_config(config, None)

        self.assertEqual("anthropic-bedrock", full_config.get("class"))
        self.assertEqual(0.2, full_config.get("temperature"))
        # The stock file computes max_tokens from max_output_tokens, and the class default does not change it.
        self.assertIsNotNone(stock_full_config.get("max_tokens"))
        self.assertEqual(stock_full_config.get("max_tokens"), full_config.get("max_tokens"))

    def test_extends_chain_takes_each_key_from_the_most_derived_class(self) -> None:
        """
        In a chain of classes that extend each other, a key takes its value from the most derived class
        that declares it, and a key that only an ancestor declares is still inherited.
        """
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info("""
            {
                "classes": {
                    "anthropic-bedrock": {
                        "args": {
                            "max_tokens": 64000,
                            "temperature": 0.2
                        }
                    },
                    "my-bedrock": {
                        "extends": "anthropic-bedrock",
                        "args": {
                            "temperature": 0.5
                        }
                    }
                }
            }
            """)
        anthropic_args: Dict[str, Any] = factory.get_chat_class_args("anthropic")

        args: Dict[str, Any] = factory.get_chat_class_args("my-bedrock")

        # Declared by my-bedrock and by both of its ancestors.
        self.assertEqual(0.5, args.get("temperature"))
        # Declared by anthropic-bedrock and by anthropic.
        self.assertEqual(64000, args.get("max_tokens"))
        # Declared only by anthropic-bedrock.
        self.assertIn("region_name", args)
        # Declared only by anthropic.
        self.assertIn("max_retries", args)
        self.assertEqual(anthropic_args.get("max_retries"), args.get("max_retries"))

    def test_extending_class_without_args_inherits_the_parent_args(self) -> None:
        """
        A class that names only the class it extends, with no "args" of its own, gets the parent's args.
        """
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info("""
            {
                "classes": {
                    "my-anthropic": {
                        "extends": "anthropic"
                    }
                }
            }
            """)

        self.assertEqual(factory.get_chat_class_args("anthropic"), factory.get_chat_class_args("my-anthropic"))

    def test_extending_class_inherits_a_parent_default_it_does_not_declare(self) -> None:
        """
        A sparse llm info file that changes an "openai" default also changes it for "azure-openai",
        which extends "openai" and does not declare that key itself.
        """
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info("""
            {
                "classes": {
                    "openai": {
                        "args": {
                            "streaming": true
                        }
                    }
                }
            }
            """)

        # The stock file leaves streaming off for both classes.
        self.assertIs(self.factory.get_chat_class_args("azure-openai").get("streaming"), False)
        self.assertIs(factory.get_chat_class_args("azure-openai").get("streaming"), True)

    def test_extending_class_dictionary_args_merge_key_by_key(self) -> None:
        """
        When a class and the class it extends both give a dictionary for the same arg, the two are merged:
        the extending class's keys win and the parent's other keys are kept.
        """
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info("""
            {
                "classes": {
                    "my-bedrock": {
                        "extends": "bedrock",
                        "args": {
                            "guardrails": {
                                "guardrailIdentifier": "my-guardrail"
                            }
                        }
                    }
                }
            }
            """)
        bedrock_guardrails: Dict[str, Any] = factory.get_chat_class_args("bedrock").get("guardrails")
        # The baseline shows the parent has other keys for the merge to keep.
        self.assertIn("guardrailVersion", bedrock_guardrails)
        expected_guardrails: Dict[str, Any] = dict(bedrock_guardrails)
        expected_guardrails["guardrailIdentifier"] = "my-guardrail"

        guardrails: Dict[str, Any] = factory.get_chat_class_args("my-bedrock").get("guardrails")

        self.assertEqual(expected_guardrails, guardrails)
        # The parent class keeps its own dictionary.
        self.assertIsNone(bedrock_guardrails.get("guardrailIdentifier"))

    def test_extending_class_null_clears_the_parent_value(self) -> None:
        """
        A class that declares an arg as null clears the value that the class it extends gives that arg.
        """
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info("""
            {
                "classes": {
                    "azure-openai": {
                        "args": {
                            "store": null
                        }
                    }
                }
            }
            """)

        # The stock file gives "openai" a store of false, which "azure-openai" inherits.
        self.assertIs(self.factory.get_chat_class_args("azure-openai").get("store"), False)
        args: Dict[str, Any] = factory.get_chat_class_args("azure-openai")

        self.assertIn("store", args)
        self.assertIsNone(args.get("store"))
        # The parent class keeps its own value.
        self.assertIs(factory.get_chat_class_args("openai").get("store"), False)

    # ---- Importing the module: the openai packages stay optional ---------------------------------

    def test_factory_module_imports_without_the_openai_packages(self) -> None:
        """
        The factory module imports even when the openai packages are not installed. The openai policies
        resolve their chat model class by name when a model is built, so an install that only uses other
        providers can leave those packages out. A child interpreter blocks them and imports the module.
        """
        repo_root: Path = Path(__file__).resolve().parents[6]
        env: Dict[str, str] = dict(os.environ)
        env["PYTHONPATH"] = str(repo_root) + os.pathsep + env.get("PYTHONPATH", "")

        command: List[str] = [sys.executable, "-c", self.IMPORT_WITHOUT_OPENAI_SCRIPT]
        result: subprocess.CompletedProcess = subprocess.run(
            command, env=env, capture_output=True, text=True, check=False, timeout=120)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("FACTORY_IMPORTED_WITHOUT_OPENAI", result.stdout)

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
