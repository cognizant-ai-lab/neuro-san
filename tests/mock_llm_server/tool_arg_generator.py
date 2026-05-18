
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
See class comment for details.
"""
from __future__ import annotations

from typing import Any
from typing import Dict
from typing import List


class ToolArgGenerator:
    """
    Utility class for fabricating minimal-valid argument values that satisfy
    an OpenAI-style tool's JSON-Schema parameters. Used by the mock LLM to
    emit plausible tool_calls without understanding the tool's semantics.
    """

    # Defaults for the simple JSON Schema primitive types that need no inspection
    # beyond their "type" field. Compound types (string/object) are handled separately.
    PRIMITIVE_DEFAULTS: Dict[str, Any] = {
        "integer": 0,
        "int": 0,
        "float": 0.0,
        "number": 0.0,
        "boolean": True,
        "array": [],
    }

    @classmethod
    def default_value_for_schema(cls, schema: Dict[str, Any]) -> Any:
        """Generate a minimal default value that satisfies a JSON Schema type."""
        schema_type = schema.get("type", "string")
        if schema_type == "string":
            enum = schema.get("enum")
            return enum[0] if enum else "test"
        if schema_type == "object":
            properties = schema.get("properties", {})
            required = schema.get("required", [])
            obj = {}
            for prop_name in required:
                prop_schema = properties.get(prop_name, {"type": "string"})
                obj[prop_name] = cls.default_value_for_schema(prop_schema)
            return obj
        # Primitives via lookup; unknown types fall back to a generic string placeholder.
        return cls.PRIMITIVE_DEFAULTS.get(schema_type, "test")

    @classmethod
    def generate_tool_args(cls, tool_schema: Dict[str, Any]) -> Dict[str, Any]:
        """Generate minimal arguments that satisfy a tool's parameter schema."""
        parameters = tool_schema.get("parameters", {})
        properties = parameters.get("properties", {})
        required = parameters.get("required", list(properties.keys()))
        args = {}
        for param_name in required:
            param_schema = properties.get(param_name, {"type": "string"})
            args[param_name] = cls.default_value_for_schema(param_schema)
        return args

    @staticmethod
    def has_tool_results(messages: List[Dict[str, Any]]) -> bool:
        """Whether the message history already contains tool-call results."""
        return any(m.get("role") == "tool" for m in messages)
