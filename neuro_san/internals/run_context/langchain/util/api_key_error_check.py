
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

from typing import Dict
from typing import List


# Dictionary with provider key env var -> strings to look for
API_KEY_EXCEPTIONS: Dict[str, List] = {
    "OPENAI_API_KEY": ["OPENAI_API_KEY", "Incorrect API key provided"],
    "ANTHROPIC_API_KEY": ["ANTHROPIC_API_KEY", "anthropic_api_key", "invalid x-api-key", "credit balance"],
    "GOOGLE_API_KEY": ["Application Default Credentials", "default credentials", "Gemini: 400 API key not valid"],

    # Azure OpenAI requires several parameters; all can be set via environment variables
    # except "deployment_name", which must be provided explicitly.
    "AZURE_OPENAI_API_KEY": ["Error code: 401", "invalid subscription key", "wrong API endpoint", "Connection error"],
    "AZURE_OPENAI_ENDPOINT": ["validation error", "base_url", "azure_endpoint", "AZURE_OPENAI_ENDPOINT",
                              "Connection error"],
    "OPENAI_API_VERSION": ["validation error", "api_version", "OPENAI_API_VERSION", "Error code: 404",
                           "Resource not found"],
    "deployment_name": ["Error code: 404", "Resource not found", "API deployment for this resource does not exist"],
}


class ApiKeyErrorCheck:
    """
    Class for common policy when checking for API key errors for various LLM providers.
    """

    @staticmethod
    def check_for_api_key_exception(exception: Exception) -> str:
        """
        :param exception: An exception to check
        :return: A more helpful exception message if it relates to an API key or None
                if it does not pertain to an API key.
        """

        exception_message: str = str(exception)
        matched_keys: List[str] = []

        # Collect all keys that have any associated string in the exception message
        # since there could be multiple keys with the exact same message.
        for api_key, string_list in API_KEY_EXCEPTIONS.items():
            for find_string in string_list:
                if find_string in exception_message:
                    matched_keys.append(api_key)
                    # No need to check the remaining strings for this key
                    break

        if matched_keys:
            keys_str = ", ".join(matched_keys)
            return f"""
A value for the {keys_str} environment variable must be correctly set in the neuro-san
server or run-time enviroment in order to use this agent network.

Some things to try:
1) Double check that your value for {keys_str} is set correctly
2) If you do not have a value for {keys_str}, visit the LLM provider's website to get one.
3) It's possible that your credit balance on your account with the LLM provider is too low
   to make the request.  Check that.
4) Sometimes these errors happen because of firewall blockages to the site that hosts the LLM.
   Try checking that you can reach the regular UI for the LLM from a web browser
   on the same machine making this request.
"""

        return None
