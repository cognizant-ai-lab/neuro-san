
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

from neuro_san.internals.run_context.langchain.core.base_model_dictionary_converter import \
    BaseModelDictionaryConverter
from neuro_san.internals.validation.network.abstract_network_validator import AbstractNetworkValidator


class PydanticParametersNetworkValidator(AbstractNetworkValidator):
    """
    AbstractNetworkValidator that validates each tool's
    function.parameters block by running the same pydantic
    BaseModelDictionaryConverter pipeline used at tool-creation time.

    Catches unrecognized type strings, malformed structures, and anything
    that would crash at runtime.  Also reports null and non-dict
    parameters blocks as structural errors.

    Expects a fully-resolved config: ParametersSchemaNetworkValidator,
    the composite that owns this validator, applies NetworkConfigFilterChain
    (commondefs, defaults, name-correction) once before running both phases.
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
        :return: A list of error messages describing pydantic conversion problems.
        """
        errors: List[str] = []

        self.logger.debug("Validating %s parameters via pydantic...", self.network_name)

        for agent_name, agent_spec in name_to_spec.items():
            params: Any = self._locate_parameters(agent_spec)

            if params is self._PARAMS_NOT_FOUND:
                # No parameters block at all - nothing to validate.
                continue
            if params is None:
                errors.append(
                    f"{agent_name}: 'parameters' is null - use {{}} or remove the key"
                )
                continue
            if not isinstance(params, dict):
                errors.append(
                    f"{agent_name}: 'parameters' must be object, "
                    f"got {type(params).__name__}"
                )
                continue

            properties: Any = params.get("properties")
            if not isinstance(properties, dict) or not properties:
                # No properties to convert - valid for zero-arg functions and
                # flat param maps. Pydantic expects properties.items(), so skip.
                continue

            preflight_errors: List[str] = PydanticParametersNetworkValidator._pre_validate_properties(
                agent_name, params,
            )
            if preflight_errors:
                errors.extend(preflight_errors)
                continue

            try:
                converter = BaseModelDictionaryConverter("parameters")
                converter.from_dict(params)
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                detail: str = " ".join(str(exc).split())
                errors.append(f"{agent_name}: pydantic model conversion failed - {detail}")
            except Exception as exc:  # pylint: disable=broad-exception-caught
                # from_dict() delegates to pydantic's create_model() and
                # recursive type resolution, which can raise unexpected
                # exception types on severely malformed input.
                detail = " ".join(str(exc).split())
                errors.append(f"{agent_name}: pydantic model conversion failed - {detail}")

        return errors

    # --- Private helpers (not overrides) ---

    @classmethod
    def _pre_validate_properties(cls, agent_name: str, params: Dict[str, Any],
                                 path: str = "parameters") -> List[str]:
        """
        Walk the properties tree looking for shapes that will crash
        BaseModelDictionaryConverter, reporting exactly which property
        is malformed and what to fix. Runs before from_dict() so that
        all property-level errors are reported in one pass with a clear
        UI, rather than crashing on the first bad property with an opaque
        Pydantic error.

        :param agent_name: Display name for error messages
        :param params: The schema dict to inspect
        :param path: Dotted path for contextual error messages
        :return: A list of actionable error messages
        """
        errors: List[str] = []
        if not isinstance(params, dict):
            return errors

        # Guard: 'properties' must be a dict when present
        properties: Any = params.get("properties")
        if properties is not None and not isinstance(properties, dict):
            errors.append(
                f"{agent_name}: {path}.properties must be an object,"
                f" got {type(properties).__name__}"
            )
            return errors

        if not isinstance(properties, dict):
            return errors

        for prop_name, prop_schema in properties.items():
            prop_path: str = f"{path}.properties.{prop_name}"
            errors.extend(
                cls._validate_schema_node(agent_name, prop_schema, prop_path)
            )

        return errors

    @classmethod
    def _validate_schema_node(cls, agent_name: str, schema: Any,
                              path: str) -> List[str]:
        """
        Validate a single schema node (null, non-dict, missing/bad type,
        array items, object properties) and recurse into children.

        :param agent_name: Display name for error messages
        :param schema: The schema value to inspect
        :param path: Dotted path for contextual error messages
        :return: A list of actionable error messages
        """
        errors: List[str] = []

        # Check 1: null property definition
        if schema is None:
            errors.append(
                f"{agent_name}: {path} is null"
                f" - define it as an object or remove the key"
            )
            return errors

        # Check 2: property definition must be a dict
        if not isinstance(schema, dict):
            errors.append(
                f"{agent_name}: {path} must be an object,"
                f" got {type(schema).__name__}"
            )
            return errors

        # Check 3: 'type' key must be present
        schema_type: Any = schema.get("type")
        if schema_type is None:
            errors.append(
                f"{agent_name}: {path} is missing 'type'"
            )
            return errors

        # Check 4: 'type' value must be a recognized string
        if not isinstance(schema_type, str):
            errors.append(
                f"{agent_name}: {path} 'type' must be a string,"
                f" got {type(schema_type).__name__}"
            )
            return errors

        if schema_type not in BaseModelDictionaryConverter.TYPE_LOOKUP:
            valid_types: str = ", ".join(
                sorted(BaseModelDictionaryConverter.TYPE_LOOKUP.keys())
            )
            errors.append(
                f"{agent_name}: {path} has unrecognized type"
                f" '{schema_type}'"
                f" - valid types are: {valid_types}"
            )
            return errors

        # Check 5: array nodes must have a valid 'items' dict
        if schema_type == "array":
            items: Any = schema.get("items")
            if items is None:
                errors.append(
                    f"{agent_name}: {path} is 'array'"
                    f" but missing 'items'"
                    f' - add "items": {{"type": "string"}} or similar'
                )
            elif not isinstance(items, dict):
                errors.append(
                    f"{agent_name}: {path}.items must be"
                    f" an object, got {type(items).__name__}"
                )
            else:
                errors.extend(
                    cls._validate_schema_node(
                        agent_name, items, f"{path}.items",
                    )
                )

        # Check 6: object nodes — validate their nested properties
        elif schema_type == "object":
            errors.extend(
                cls._pre_validate_properties(
                    agent_name, schema, path,
                )
            )

        return errors
