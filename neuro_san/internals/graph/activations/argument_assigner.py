
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

import json


class ArgumentAssigner:
    """
    Class which puts the text together for passing function arguments
    information from one agent to the next.
    """

    def assign(self, arguments: Dict[str, Any]) -> List[str]:
        """
        :param arguments: The arguments dictionary with the values as determined
                by the calling agent.
        :return: A List of text that describes the values of each argument,
                suitable for transmitting to the chat stream of another agent.
        """
        assignments: List[str] = []

        # Start to build the list of assignments, with one sentence for each argument
        for args_name, args_value in arguments.items():

            # Skip if the value of the argument is None or empty
            if args_value in (None, "", [], {}):
                continue

            args_value_str: str = self.get_args_value_as_string(args_value)

            # No specific attribution text, so we make up a boilerplate
            # one where it give the arg name <is/are> and the value.

            # Figure out the attribution verb for singular vs plural
            assignment_verb: str = "is"
            if isinstance(args_value, (dict, list)):
                assignment_verb = "are"

            # Put together the assignment statement
            assignment: str = f"The {args_name} {assignment_verb} {args_value_str}."

            assignments.append(assignment)

        return assignments

    def get_args_value_as_string(self, args_value: Any) -> str:
        """
        Convert an argument value to a formatted string representation.

        Handles various input types to produce a string suitable for insertion into
        prompts or code templates, while minimizing formatting issues such as
        unwanted placeholder interpretation (e.g., curly braces).

        - For dictionaries: returns a JSON-style string with outer braces removed.
        - For lists: recursively stringifies each element and joins them with commas.
        - For strings: wraps in single quotes and escapes curly braces (for templating).
        - For other types: falls back to str().

        :param args_value: The argument value to convert.
        :return: A string representation of the argument.
        """
        args_value_str: str = None

        if isinstance(args_value, dict):
            args_value_str = json.dumps(args_value)
            # Strip the begin/end braces as gpt-4o doesn't like them.
            # This means that anything within the json-y braces for a dictionary
            # value gets interpreted as "this is an input value that has
            # to come from the code" when that is not the case at all.
            # Unclear why this is an issue with gpt-4o and not gpt-4-turbo.
            args_value_str = args_value_str[1:-1]

        elif isinstance(args_value, list):
            str_values = []
            for item in args_value:
                item_str: str = self.get_args_value_as_string(item)
                str_values.append(item_str)
            args_value_str = ", ".join(str_values)

        elif isinstance(args_value, str):
            # For a long time, this had been:
            #       args_value_str = f'"{args_value}"'
            # ... but as of 6/19/25 we are experimenting with new quoting
            #   in an attempt to reduce crazy JSON escaping
            args_value_str = f"'{args_value}'"
            # Per https://github.com/langchain-ai/langchain/issues/1660
            # We need to use double curly braces in order to pass values
            # that actually have curly braces in them so they will not
            # be mistaken for string placeholders for input.
            args_value_str = args_value_str.replace("{", "{{")
            args_value_str = args_value_str.replace("}", "}}")

        else:
            args_value_str = str(args_value)

        return args_value_str
