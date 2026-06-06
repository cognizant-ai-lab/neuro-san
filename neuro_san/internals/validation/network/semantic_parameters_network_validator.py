
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

from logging import getLogger
from logging import Logger
from typing import Any
from typing import Dict
from typing import List

from neuro_san.internals.validation.network.abstract_network_validator import AbstractNetworkValidator


class SemanticParametersNetworkValidator(AbstractNetworkValidator):
    """
    AbstractNetworkValidator performing custom semantic checks on each
    tool's function.parameters block that pydantic conversion cannot detect:

      * A nested 'parameters' key (the headline bug from studio#690).
        Pydantic treats this as just another property.
      * ``required`` entries that reference undefined properties.
        Pydantic silently ignores these.

    Both checks recurse into nested object properties and array items
    via ``_iter_subschemas()`` so mistakes at any depth are caught.
    """

    def __init__(self, network_name: str = None):
        """
        Constructor

        :param network_name: The agent network name for diagnostic log lines
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.network_name: str = network_name

    # --- Override ---

    # Overrides AbstractNetworkValidator.validate_name_to_spec_dict
    def validate_name_to_spec_dict(self, name_to_spec: Dict[str, Any]) -> List[str]:
        """
        :param name_to_spec: The name -> agent spec dictionary to validate
        :return: A list of error messages describing semantic parameter problems.
        """
        errors: List[str] = []

        self.logger.debug("Validating %s parameters semantics...", self.network_name)

        for agent_name, agent_spec in name_to_spec.items():
            params: Any = self._locate_parameters(agent_spec)

            if not isinstance(params, dict):
                # Null, missing, or non-dict parameters are reported by
                # PydanticParametersNetworkValidator.  Skip silently here.
                continue

            for nested_path in self._find_nested_parameters_keys(params):
                errors.append(
                    f"{agent_name}: '{nested_path}' contains a nested "
                    f"'parameters' key - move the inner 'properties' "
                    f"and 'required' up one level"
                )
            errors.extend(self._check_required_refs(agent_name, params))

        return errors

    # --- Private helpers (not overrides) ---

    @staticmethod
    def _iter_subschemas(schema: Any, path: str):
        """
        Yield ``(child_schema, child_path)`` for every nested object
        property and array ``items`` entry inside *schema*.
        """
        properties: Any = schema.get("properties")
        if isinstance(properties, dict):
            for prop_name, prop_schema in properties.items():
                if isinstance(prop_schema, dict):
                    yield prop_schema, f"{path}.properties.{prop_name}"

        items: Any = schema.get("items")
        if isinstance(items, dict):
            yield items, f"{path}.items"

    @classmethod
    def _check_required_refs(cls, agent_name: str, params: Any,
                             path: str = "parameters") -> List[str]:
        """
        Recursively verify that every ``required`` entry references a
        key that exists in ``properties``.  Pydantic silently ignores
        missing required entries, so this must remain a custom check.

        :param agent_name: Display name for error messages
        :param params: The schema dict to validate
        :param path: Dotted path for contextual error messages
        :return: A list of error messages
        """
        errors: List[str] = []
        if not isinstance(params, dict):
            return errors

        properties: Any = params.get("properties")
        required: Any = params.get("required")
        if isinstance(required, list) and isinstance(properties, dict):
            missing: List[str] = [r for r in required if r not in properties]
            if missing:
                errors.append(
                    f"{agent_name}: {path}.required has undefined props {missing}"
                )

        for child, child_path in cls._iter_subschemas(params, path):
            errors.extend(cls._check_required_refs(
                agent_name, child, child_path,
            ))

        return errors

    @classmethod
    def _find_nested_parameters_keys(cls, schema: Any,
                                     path: str = "parameters") -> List[str]:
        """
        Walk a JSON-schema-like tree, returning every dotted path whose dict
        contains a 'parameters' key.  Does not recurse into the 'parameters'
        value itself - once we've flagged a site as malformed, we leave the
        inner contents alone (fixing the outer occurrence likely fixes the
        inner ones, and reporting both would be noisy).
        """
        found: List[str] = []
        if not isinstance(schema, dict):
            return found

        if "parameters" in schema:
            found.append(path)

        for child, child_path in cls._iter_subschemas(schema, path):
            found.extend(cls._find_nested_parameters_keys(child, child_path))

        return found
