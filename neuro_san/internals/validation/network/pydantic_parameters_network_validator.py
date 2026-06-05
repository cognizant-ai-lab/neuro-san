
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


class PydanticParametersNetworkValidator(AbstractNetworkValidator):
    """
    AbstractNetworkValidator that validates each tool's
    function.parameters block by running the same pydantic
    BaseModelDictionaryConverter pipeline used at tool-creation time.

    Catches unrecognized type strings, malformed structures, and anything
    that would crash at runtime.  Also reports null and non-dict
    parameters blocks as structural errors.

    Unresolved string ``items`` references (from missing commondefs)
    are sanitized to a permissive dict before pydantic sees them.
    """

    # Sentinel returned by _locate_parameters meaning "the key is present but
    # explicitly null". The caller flags this rather than silently skipping.
    # object() is identity-safe - cannot collide with any real config value.
    _EXPLICIT_NULL: Any = object()

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
            display_name: str = self._resolve_agent_name(agent_name, agent_spec)
            params: Any = self._locate_parameters(agent_spec)

            if params is None:
                # No parameters block at all - nothing to validate.
                continue
            if params is self._EXPLICIT_NULL:
                errors.append(
                    f"{display_name}: 'parameters' is null - use {{}} or remove the key"
                )
                continue
            if not isinstance(params, dict):
                errors.append(
                    f"{display_name}: 'parameters' must be object, "
                    f"got {type(params).__name__}"
                )
                continue

            properties: Any = params.get("properties")
            if not isinstance(properties, dict) or not properties:
                # No properties to convert - valid for zero-arg functions and
                # flat param maps. Pydantic expects properties.items(), so skip.
                continue

            sanitized: Dict[str, Any] = self._sanitize_for_pydantic(params)
            try:
                converter = BaseModelDictionaryConverter("parameters")
                converter.from_dict(sanitized)
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                detail: str = " ".join(str(exc).split())
                errors.append(f"{display_name}: pydantic model conversion failed - {detail}")
            except Exception as exc:  # pylint: disable=broad-exception-caught
                # from_dict() delegates to pydantic's create_model() and
                # recursive type resolution, which can raise unexpected
                # exception types on severely malformed input.
                detail = " ".join(str(exc).split())
                errors.append(f"{display_name}: pydantic model conversion failed - {detail}")

        return errors

    # --- Private helpers (not overrides) ---

    @staticmethod
    def _resolve_agent_name(agent_name: Optional[str], agent_spec: Any) -> str:
        """
        Fall back to function.name when the name_to_spec key is None so that
        error messages identify the right tool.
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
          - cls._EXPLICIT_NULL: the key is present but explicitly null
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
    def _sanitize_for_pydantic(cls, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Return a deep copy of *schema* with string ``items`` references
        replaced by a permissive dict.  The runtime pipeline resolves
        these via DictionaryCommonDefsConfigFilter before pydantic ever
        sees them, but unresolved references can appear if a commondef
        is missing or during direct validation calls.
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
