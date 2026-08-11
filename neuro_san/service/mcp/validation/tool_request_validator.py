
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
from typing import Set

import copy
import re
import jsonschema

from leaf_common.validation.dictionary_validator import DictionaryValidator


class ToolRequestValidator(DictionaryValidator):
    """
    Class implementing MCP tool call request validation against tool call schema.
    """
    def __init__(self, service_schema: Dict[str, Any]):
        """
        Initialize the tool request validator.
        :param service_schema: The OpenAPI schema dictionary for the neuro-san service API.
        """
        self.tool_request_method = "ChatRequest"
        self.required_property = "user_message"
        # Generate the validation schema for tool call requests
        # from the overall neuro-san service schema:
        self.request_schema = self._extract_sub_schema(
            service_schema,
            self.tool_request_method,
            self.required_property)

    def validate(self, candidate: Dict[str, Any]) -> List[str]:
        """
        Validate the dictionary data of an incoming tool call request against MCP protocol schema.
        :param candidate: The request dictionary to validate
        :return: A list of error messages, if any
        """
        try:
            jsonschema.validate(instance=candidate, schema=self.request_schema)
        except jsonschema.exceptions.ValidationError:
            # We don't return detailed validation errors to a client,
            # since they tend to be very long and complex.
            return [f"Request validation FAILED for tool call request: {candidate}"]
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return [f"Validation exception: {str(exc)}"]
        return None

    def get_request_schema(self) -> Dict[str, Any]:
        """
        :return: The tool request validation schema
        """
        return self.request_schema

    def _get_schema_defs(self, schema: Dict[str, Any]) -> Set[str]:
        """
        Return the set of referenced schema names found in json schema via $ref.

        Recognizes local refs of the form:
          - "#/components/schemas/Name"
        """
        _ref_defs_re = re.compile(r"^#/components/schemas/([^/]+)$")
        out: Set[str] = set()

        def visit(node: Any):
            if isinstance(node, dict):
                # Collect $ref if present
                ref = node.get("$ref")
                if isinstance(ref, str):
                    m_ref = _ref_defs_re.match(ref)
                    if m_ref:
                        out.add(m_ref.group(1))
                # Recurse through all values (including keys like allOf/anyOf/etc.)
                for v in node.values():
                    visit(v)
            elif isinstance(node, list):
                for item in node:
                    visit(item)
            # primitives: nothing to do

        visit(schema)
        return out

    def _get_next(self, items: Dict[str, bool]) -> str:
        """
        Returns the next unprocessed item in the provided dictionary.
        Iterates through the given dictionary to find the first key whose value
        is `False`, indicating it has not yet been processed.
        :param items: A dictionary where keys are items being processed
                      and values are booleans indicating if the item has been processed.
        :return: The key of the first unprocessed item, or `None` if all items are done.
        """
        for item, processed in items.items():
            if not processed:
                return item
        return None

    def _get_all_defs(self, root_item: str, schemas: Dict[str, Any]) -> Set[str]:
        """
        :param root_item: The root item to start processing from
        :param schemas: The json schemas dictionary to process
        :return: A set of all item names which were recursively referenced by the given root item
        """
        items: Dict[str, bool] = {root_item: False}
        processing: bool = True
        while processing:
            next_item = self._get_next(items)
            if next_item:
                items[next_item] = True  # Mark as being processed
                next_schema: Dict[str, Any] = schemas.get(next_item)
                if not next_schema:
                    raise ValueError(f"No schema found for {next_item}")
                referenced_defs = self._get_schema_defs(next_schema)
                for ref in referenced_defs:
                    if ref not in items:
                        items[ref] = False
            else:
                processing = False
        return set(items)

    def _extract_sub_schema(self, schema: Dict[str, Any], root_item: str, required_property: str) -> Dict[str, Any]:
        """
        Extracts a sub-schema from the given OpenAPI schema, starting from the given root item.
        """
        result: Dict[str, Any] = {}
        # Get all the schema definitions:
        schemas: Dict[str, Any] = schema.get("components", {}).get("schemas", {})
        if not schemas:
            raise ValueError("No components found in schema")
        item_schema: Dict[str, Any] = schemas.get(root_item, {})
        if not item_schema:
            raise ValueError(f"No schema found for {root_item}")
        result["components"] = {"schemas": copy.deepcopy(schemas)}
        referenced_defs = self._get_all_defs(root_item, schemas)
        # To reduce the overall size of the resulting schema,
        # remove all schemas that are not referenced by the root item.
        for one_schema in schemas:
            if one_schema not in referenced_defs:
                del result["components"]["schemas"][one_schema]
        # Add required properties to the root schema
        root_schema = result["components"]["schemas"][root_item]
        root_schema["required"] = [required_property]
        # Make tool call schema strict - no additional properties allowed
        root_schema["additionalProperties"] = False
        result["$ref"] = f"#/components/schemas/{root_item}"
        return result
