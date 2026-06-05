
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
from typing import Any
from typing import Dict
from typing import List

from neuro_san.internals.interfaces.schema_conversion_validator import SchemaConversionValidator
from neuro_san.internals.run_context.langchain.core.base_model_dictionary_converter import \
    BaseModelDictionaryConverter


class PydanticSchemaConversionValidator(SchemaConversionValidator):
    """
    SchemaConversionValidator that attempts the same pydantic
    BaseModelDictionaryConverter pipeline used at tool-creation time.

    Lives in the run_context.langchain layer because it depends on
    BaseModelDictionaryConverter and pydantic internals.
    """

    # Overrides SchemaConversionValidator.try_convert
    def try_convert(self, params: Dict[str, Any]) -> List[str]:
        """
        Attempt the same pydantic conversion that runs at tool-creation
        time (BaseModelDictionaryConverter.from_dict).  If it crashes,
        the schema would crash at runtime too.

        :param params: The parameters dict to validate
        :return: A list of error messages (empty when conversion succeeds)
        """
        properties: Any = params.get("properties")
        if not isinstance(properties, dict) or not properties:
            # No properties to convert - valid for zero-arg functions and
            # flat param maps. Pydantic expects properties.items(), so skip.
            return []

        sanitized: Dict[str, Any] = self._sanitize_for_pydantic(params)
        try:
            converter = BaseModelDictionaryConverter("parameters")
            converter.from_dict(sanitized)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            detail: str = " ".join(str(exc).split())
            return [f"pydantic model conversion failed - {detail}"]
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # from_dict() delegates to pydantic's create_model() and
            # recursive type resolution, which can raise unexpected
            # exception types on severely malformed input.
            detail = " ".join(str(exc).split())
            return [f"pydantic model conversion failed - {detail}"]
        return []

    # --- Private helpers ---

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
