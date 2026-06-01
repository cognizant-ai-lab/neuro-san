
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

from copy import deepcopy
from logging import getLogger
from logging import Logger
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from neuro_san.internals.run_context.langchain.core.base_model_dictionary_converter import \
    BaseModelDictionaryConverter
from neuro_san.internals.validation.network.abstract_network_validator import AbstractNetworkValidator


class ParametersShapeNetworkValidator(AbstractNetworkValidator):
    """
    AbstractNetworkValidator that checks the shape of each tool's
    function.parameters (or top-level parameters) block.

    Validation is split into two phases:

    Phase 1 — **Pydantic conversion**: attempts the same
    BaseModelDictionaryConverter pipeline that runs at tool-creation time.
    Any type string, structural issue, or recursion problem that would
    crash the runtime is caught here.

    Phase 2 — **Custom semantic checks** that pydantic cannot detect:
      * A nested 'parameters' key (the headline bug from studio#690).
      * ``required`` entries that reference undefined properties.

    Both phases recurse into nested object properties and array items so
    mistakes at any depth are caught.
    """

    # Sentinel returned by _locate_parameters meaning "the key is present but
    # explicitly null". The caller flags this rather than silently skipping.
    # object() is identity-safe — cannot collide with any real config value.
    _EXPLICIT_NULL: Any = object()

    def __init__(self):
        self.logger: Logger = getLogger(self.__class__.__name__)

    # Overrides AbstractNetworkValidator.validate_name_to_spec_dict
    def validate_name_to_spec_dict(self, name_to_spec: Dict[str, Any]) -> List[str]:
        """
        :param name_to_spec: The name -> agent spec dictionary to validate
        :return: A list of error messages describing parameters-shape problems.
        """
        errors: List[str] = []

        self.logger.debug("Validating parameters shape...")

        for agent_name, agent_spec in name_to_spec.items():
            display_name: str = self._resolve_agent_name(agent_name, agent_spec)
            params: Any = self._locate_parameters(agent_spec)

            if params is None:
                # No parameters block at all — nothing to validate.
                continue
            if params is self._EXPLICIT_NULL:
                errors.append(
                    f"{display_name}: 'parameters' is null — use {{}} or remove the key"
                )
                continue
            if not isinstance(params, dict):
                errors.append(
                    f"{display_name}: 'parameters' must be object, "
                    f"got {type(params).__name__}"
                )
                continue

            # Phase 1: Pydantic structural validation (types, recursion)
            errors.extend(self._try_pydantic_conversion(display_name, params))

            # Phase 2: Custom neuro-san-specific checks
            for nested_path in self._find_nested_parameters_keys(params):
                errors.append(
                    f"{display_name}: '{nested_path}' contains a nested "
                    f"'parameters' key — move the inner 'properties' "
                    f"and 'required' up one level"
                )
            errors.extend(self._check_required_refs(display_name, params))

        if len(errors) > 0:
            self.logger.error(str(errors))

        return errors

    @staticmethod
    def _resolve_agent_name(agent_name: Optional[str], agent_spec: Any) -> str:
        """
        AbstractNetworkValidator.get_name_to_spec keys agents by
        agent_spec.get("name"), which yields None when an agent only sets
        function.name. Fall back to function.name so the error message
        identifies the right tool — otherwise the user sees "None: ..." in
        the welcome-replacement message and cannot tell which agent broke.
        """
        if agent_name:
            return agent_name
        if isinstance(agent_spec, dict):
            function_block: Any = agent_spec.get("function")
            if isinstance(function_block, dict):
                fn_name: Any = function_block.get("name")
                if fn_name:
                    return fn_name
        return "<unnamed>"

    @classmethod
    def _locate_parameters(cls, agent_spec: Any) -> Any:
        """
        Pull the parameters block off an agent spec, whether it lives at
        function.parameters (OpenAI-style) or at the top level.

        Returns:
          - dict: the parameters block to validate
          - None: no parameters block present (validator skips silently)
          - cls._EXPLICIT_NULL: the key is present but explicitly null;
                the caller flags this rather than silently skipping
        """
        if not isinstance(agent_spec, dict):
            return None
        function_block: Any = agent_spec.get("function")
        if isinstance(function_block, dict) and "parameters" in function_block:
            value: Any = function_block.get("parameters")
            return cls._EXPLICIT_NULL if value is None else value
        if "parameters" in agent_spec:
            value = agent_spec.get("parameters")
            return cls._EXPLICIT_NULL if value is None else value
        return None

    @classmethod
    def _try_pydantic_conversion(cls, agent_name: str,
                                 params: Dict[str, Any]) -> List[str]:
        """
        Attempt the same pydantic conversion that runs at tool-creation
        time (BaseModelDictionaryConverter.from_dict). If it crashes, the
        schema would crash at runtime too.

        :param agent_name: Display name for error messages
        :param params: The parameters dict to validate
        :return: A list of error messages (empty when conversion succeeds)
        """
        properties: Any = params.get("properties")
        if not isinstance(properties, dict) or not properties:
            # No properties to convert — valid for zero-arg functions and
            # flat param maps. Pydantic expects properties.items(), so skip.
            return []

        sanitized: Dict[str, Any] = cls._sanitize_for_pydantic(params)
        try:
            converter = BaseModelDictionaryConverter("parameters")
            converter.from_dict(sanitized)
        except (AttributeError, KeyError, TypeError, ValueError,
                RuntimeError) as exc:
            detail: str = " ".join(str(exc).split())
            return [f"{agent_name}: pydantic model conversion failed — {detail}"]
        return []

    @classmethod
    def _sanitize_for_pydantic(cls, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Return a deep copy of *schema* with string ``items`` references
        replaced by a permissive dict.  The runtime pipeline resolves
        these via DictionaryCommonDefsConfigFilter before pydantic ever
        sees them, but the validator may run on raw unit-test dicts.
        """
        result: Dict[str, Any] = deepcopy(schema)
        cls._replace_string_items(result)
        return result

    @classmethod
    def _replace_string_items(cls, schema: Any) -> None:
        """Recursively replace string ``items`` values with ``{type: string}``."""
        if not isinstance(schema, dict):
            return
        items: Any = schema.get("items")
        if isinstance(items, str):
            schema["items"] = {"type": "string"}
        elif isinstance(items, dict):
            cls._replace_string_items(items)
        properties: Any = schema.get("properties")
        if isinstance(properties, dict):
            for prop_schema in properties.values():
                cls._replace_string_items(prop_schema)

    @staticmethod
    def _iter_subschemas(schema: Any, path: str):
        """
        Yield ``(child_schema, child_path)`` for every nested object
        property and array ``items`` entry inside *schema*.  Both
        ``_check_required_refs`` and ``_find_nested_parameters_keys``
        share this traversal.
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
        contains a 'parameters' key. Does not recurse into the 'parameters'
        value itself — once we've flagged a site as malformed, we leave the
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
