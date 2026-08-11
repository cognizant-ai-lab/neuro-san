
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
"""
See class comment for details
"""
from typing import Any
from typing import Dict
from typing import List

import jsonschema

from leaf_common.validation.dictionary_validator import DictionaryValidator


class McpRequestValidator(DictionaryValidator):
    """
    Class implementing MCP request validation against MCP protocol schema.
    """
    def __init__(self, validation_schema: Dict[str, Any]):
        self.validation_schema = validation_schema

    def validate(self, candidate: Dict[str, Any]) -> List[str]:
        """
        Validate the dictionary data of incoming MCP request against MCP protocol schema.
        :param candidate: The request dictionary to validate
        :return: A list of error messages, if any
        """
        try:
            jsonschema.validate(instance=candidate, schema=self.validation_schema)
        except jsonschema.exceptions.ValidationError:
            # We don't return detailed validation errors to the client,
            # since they tend to be very long and complex.
            return [f"Request validation FAILED for MCP request: {candidate}"]
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return [f"Validation exception: {str(exc)}"]
        return None
