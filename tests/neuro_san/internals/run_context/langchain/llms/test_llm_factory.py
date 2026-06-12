
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

from tests.neuro_san.internals.run_context.langchain.llms.custom_llm_factory import CustomLlmFactory


class TestLlmFactory:
    """
    Test creating custom Factory class for LLM operations
    """

    def test_llm_factory(self):
        """
        This method specifies the default LlmPolicy class that will be used for any LLMs
        instantiated by this factory that don't specify an llm_policy_class in their config.
        """
        _ = CustomLlmFactory()

