
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

from copy import deepcopy

from neuro_san.internals.graph.filters.abstract_common_defs_config_filter \
    import AbstractCommonDefsConfigFilter


class DictionaryCommonDefsConfigFilter(AbstractCommonDefsConfigFilter):
    """
    An AbstractCommonDefsConfigFilter implementation that takes a agent tool
    registry config that may or may not contain commondefs definitions
    for dictionaries to substitute in by key.

    For example: Say in the config there is a top-level definition:

        "commondefs": {
            "replacement_values": {
                "foo": {
                    "bar": 1
                }
            }
        }

    This ConfigFilter implementation will replace any value of the string value "foo"
    with the full dictionary { "bar": 1 }.
    """

    def __init__(self, replacements: Dict[str, Any] = None):
        """
        Constructor

        :param replacements: An initial replacements dictionary to start out with
                whose (copied) contents will be updated with commondefs definitions
                in the basis_config during the filter_config() entry point.
                Default is None, indicating everything needed comes from the config.
        """
        super().__init__("replacement_values", replacements)

    def make_replacements(self, source_value: Any, replacements: Dict[str, Any]) -> Any:
        """
        Make replacements per the keys and values in the replacements dictionary

        :param source_value: The value to potentially do replacements on
        :param replacements: A dictionary of string keys to their replacements
        :return: A potentially new value if some key in the replacements dictionary
                is found to trigger a replacement, otherwise, the same source_value
                that came in.
        """

        if not isinstance(source_value, str):
            # We only modify strings in this implementation.
            # Let everything else go through unadulterated.
            return source_value

        # If the value is a string, we might have a candidate for replacement
        replacement_value: Any = replacements.get(source_value)
        if replacement_value is None:

            # Nothing in the dicitonary of replacements.
            # Leave the string as-is.
            # Move along. Nothing to see here.
            return source_value

        # Make a deepcopy in case the replacement is something
        # that gets modified independently by other filtering steps.
        replacement_value_copy: Any = deepcopy(replacement_value)

        return replacement_value_copy
