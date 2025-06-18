
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
    "GOOGLE_API_KEY": ["Application Default Credentials", "default credentials"],
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
        api_key: str = None

        # Search for strings in the exception message
        found = False
        for api_key, string_list in API_KEY_EXCEPTIONS.items():
            for find_string in string_list:
                if find_string in exception_message:
                    found = True
                    break
            if found:
                break

        if found:
            return f"""
A value for the {api_key} environment variable must be correctly set in the neuro-san
server or run-time enviroment in order to use this agent network.

Some things to try:
1) Double check that your value for {api_key} is set correctly
2) If you do not have a value for {api_key}, visit the LLM provider's website to get one.
3) It's possible that your credit balance on your account with the LLM provider is too low
   to make the request.  Check that.
4) Sometimes these errors happen because of firewall blockages to the site that hosts the LLM.
   Try checking that you can reach the regular UI for the LLM from a web browser
   on the same machine making this request.
"""

        return None
