
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
from typing import Any
from typing import Dict
from unittest import TestCase
from unittest.mock import MagicMock
from unittest.mock import patch

from neuro_san.internals.run_context.langchain.llms.llm_policy import LlmPolicy


class TestLlmPolicy(TestCase):
    """
    Tests for the framework methods on the LlmPolicy base class.
    """

    def test_model_name_wins_over_the_other_keys(self) -> None:
        """
        "model_name" is read first when several model keys are set.
        """
        config: Dict[str, Any] = {"model_name": "first", "model": "second", "model_id": "third"}
        self.assertEqual(LlmPolicy.get_model_name(config), "first")

    def test_model_is_the_first_fallback(self) -> None:
        """
        "model" is read when "model_name" is missing or empty.
        """
        self.assertEqual(LlmPolicy.get_model_name({"model": "second", "model_id": "third"}), "second")
        self.assertEqual(LlmPolicy.get_model_name({"model_name": None, "model": "second"}), "second")

    def test_model_id_is_the_last_fallback(self) -> None:
        """
        "model_id" is read when neither of the other keys names a model.
        """
        self.assertEqual(LlmPolicy.get_model_name({"model_id": "third"}), "third")
        self.assertEqual(LlmPolicy.get_model_name({"model_name": "", "model": None, "model_id": "third"}), "third")

    def test_none_when_no_key_names_a_model(self) -> None:
        """
        A config without any model key gives None rather than raising.
        """
        self.assertIsNone(LlmPolicy.get_model_name({}))
        self.assertIsNone(LlmPolicy.get_model_name({"class": "openai", "model_name": None}))

    def test_create_llm_gets_the_name_get_model_name_reads(self) -> None:
        """
        create_llm_resources_components() hands create_llm() the same name get_model_name() returns.
        """
        config: Dict[str, Any] = {"class": "openai", "model": "from-model-key"}
        policy: LlmPolicy = LlmPolicy()
        llm: MagicMock = MagicMock(name="llm")
        with patch.object(LlmPolicy, "create_llm", return_value=llm) as create_llm:
            created, returned_policy = policy.create_llm_resources_components(config)

        # The base create_client() returns None, so the llm is kept on the policy for later cleanup.
        create_llm.assert_called_once_with(config, "from-model-key", None)
        self.assertIs(created, llm)
        self.assertIs(returned_policy, policy)
        self.assertIs(policy.llm, llm)
