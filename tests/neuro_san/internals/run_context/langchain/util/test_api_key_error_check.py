
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

from typing import Optional
from unittest import TestCase

from neuro_san.internals.run_context.langchain.util.api_key_error_check import ApiKeyErrorCheck


class TestApiKeyErrorCheck(TestCase):
    """
    Test cases for ApiKeyErrorCheck, centred on the Azure OpenAI rows of its guidance table.
    """

    # The 404 body Azure's v1 API returned for an unknown deployment (recorded live on 2026-09-28).
    AZURE_V1_UNKNOWN_DEPLOYMENT: str = ("Error code: 404 - {'error': {'type': 'invalid_request_error', "
                                        "'code': 'DeploymentNotFound', 'message': 'The API deployment for this "
                                        "resource does not exist. If you created the deployment within the last "
                                        "5 minutes, please wait a moment and try again.'}}")

    def test_azure_v1_unknown_deployment_maps_to_the_deployment_variable(self) -> None:
        """
        The v1 API's DeploymentNotFound answer produces the AZURE_OPENAI_DEPLOYMENT_NAME guidance.
        """
        hint: Optional[str] = ApiKeyErrorCheck.check_for_api_key_exception(Exception(self.AZURE_V1_UNKNOWN_DEPLOYMENT))

        self.assertIsNotNone(hint)
        self.assertIn("AZURE_OPENAI_DEPLOYMENT_NAME", hint)
        self.assertNotIn("AZURE_OPENAI_API_KEY", hint)

    def test_error_code_alone_is_enough(self) -> None:
        """
        The code string matches on its own, so a trimmed or reformatted message still gets the guidance.
        """
        hint: Optional[str] = ApiKeyErrorCheck.check_for_api_key_exception(Exception("DeploymentNotFound"))

        self.assertIsNotNone(hint)
        self.assertIn("AZURE_OPENAI_DEPLOYMENT_NAME", hint)

    def test_policy_credential_error_names_both_key_variables(self) -> None:
        """
        AzureLlmPolicy's credential error names AZURE_OPENAI_API_KEY, which also contains OPENAI_API_KEY, so the
        guidance lists both: the OpenAI key really is the documented fallback.
        """
        message: str = ("Azure OpenAI needs a credential: set openai_api_key in llm_config or the "
                        "AZURE_OPENAI_API_KEY environment variable (OPENAI_API_KEY is used as a fallback)")
        hint: Optional[str] = ApiKeyErrorCheck.check_for_api_key_exception(Exception(message))

        self.assertIsNotNone(hint)
        self.assertIn("AZURE_OPENAI_API_KEY", hint)
        self.assertIn("OPENAI_API_KEY", hint)

    def test_unrelated_error_gets_no_guidance(self) -> None:
        """
        An exception that matches no row and is not a pydantic ValidationError yields None.
        """
        hint: Optional[str] = ApiKeyErrorCheck.check_for_api_key_exception(RuntimeError("connection reset by peer"))

        self.assertIsNone(hint)
