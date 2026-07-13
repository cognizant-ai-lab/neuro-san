
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


class ExceptionUtil:
    """
    Utilities to deal with exceptions.
    """

    @staticmethod
    def get_exception_details(exception: Exception, indent: int = 0) -> str:
        """
        Recursively extract detailed information from nested exceptions.

        This function handles both regular exceptions and ExceptionGroup instances
        (introduced in Python 3.11) which can contain multiple nested exceptions.
        It creates a human-readable, hierarchical representation of all exceptions
        in the error chain.

        :param exception: The exception to analyze. Can be any Exception type,
                            including ExceptionGroup instances that contain multiple
                            nested exceptions.
        :param indent: The current indentation level for formatting.
                                Each recursive call increases this by 1 to create
                                a visual hierarchy. Defaults to 0.

        :return: A formatted string containing the exception type, message, and
                any nested sub-exceptions with proper indentation to show the
                hierarchy. Each line ends with a newline character.

        Note:
            This function is particularly useful for debugging MCP (Model Context Protocol)
            errors and other complex exception scenarios where multiple errors can occur
            simultaneously and get wrapped in ExceptionGroup containers.
        """

        # Create indentation string based on current nesting level
        # Each level adds 2 spaces for visual hierarchy
        spaces: str = "  " * indent

        # Start building the message with exception type and description
        # Format: "ExceptionType: exception message"
        message: str = f"{spaces}{type(exception).__name__}: {exception}\n"

        # Check if this exception is an ExceptionGroup (Python 3.11+ feature)
        # ExceptionGroup can contain multiple exceptions that occurred simultaneously
        if isinstance(exception, ExceptionGroup):
            # Iterate through each sub-exception in the group
            for i, sub_exc in enumerate(exception.exceptions):
                # Add a header for each sub-exception with 1-based numbering
                message += f"{spaces}Sub-exception {i+1}:\n"

                # Recursively process the sub-exception with increased indentation
                # This handles cases where sub-exceptions might themselves be ExceptionGroups
                message += ExceptionUtil.get_exception_details(sub_exc, indent + 1)

        return message
