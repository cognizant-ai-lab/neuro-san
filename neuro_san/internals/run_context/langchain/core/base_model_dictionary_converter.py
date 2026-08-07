
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
from __future__ import annotations

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Type
from typing import Union

from pydantic import BaseModel
from pydantic import Field
from pydantic import create_model

from leaf_common.serialization.interface.dictionary_converter import DictionaryConverter

from neuro_san.internals.run_context.langchain.core.tool_spec_error import ToolSpecError


class BaseModelDictionaryConverter(DictionaryConverter):
    """
    DictionaryConverter implementation which can convert an OpenAI
    function spec (the dictionary) into a pydantic BaseModel
    which describes the same object structure or "shape".
    """

    TYPE_LOOKUP: Dict[str, Type] = {
        "string": str,
        "int": int,
        "float": float,
        "boolean": bool,
        "array": List,

        # Aliases so that standard JSON Schema / OpenAI function spec type
        # names work as well as the HOCON-native names above.
        # "number" maps to a union because JSON Schema's number covers both
        # integers and floats, and pydantic's smart-mode union preserves
        # whichever one the caller actually sent.
        "integer": int,
        "number": Union[int, float],
        "bool": bool,

        # Note: This entry only applies to "object" properties that do not
        #       declare "properties" of their own.  Objects that do declare
        #       them never reach this lookup - get_type_from_property_dict()
        #       below converts those into nested pydantic BaseModels, and
        #       PydanticArgumentDictionaryConverter flattens any such nested
        #       models back into plain dictionaries before tool arguments
        #       are passed along, so CodedTools always receive dictionaries.
        #
        #       Dict[str, Any] is used here rather than bare Any because of
        #       the JSON schema each produces for the LLM provider:
        #       * Any yields an empty schema ({}), which provider adapters
        #         cannot represent faithfully.  Notably langchain-google-genai
        #         (every version tested, 2.1.8 through 4.3.2) defaults such
        #         untyped properties to STRING, after which Gemini sends
        #         JSON-encoded strings where tools expect dictionaries.
        #       * Dict[str, Any] yields
        #         {"type": "object", "additionalProperties": true},
        #         which converts to a proper OBJECT declaration everywhere.
        #
        #       For well-formed arguments the two behave identically: a
        #       dictionary sent by the LLM reaches the tool as the same
        #       plain dict.  Non-dict values (e.g. a JSON-encoded string),
        #       which Any silently passed through with the wrong type, now
        #       fail pydantic validation and are reported back to the LLM
        #       as a correctable tool error instead.
        "object": Dict[str, Any]
    }

    def __init__(self, top_level_field_name: str):
        """
        Constructor

        :param top_level_field_name: The field name for the top-level object
        """
        self.top_level_field_name: str = top_level_field_name

    def to_dict(self, obj: BaseModel) -> Dict[str, Any]:
        """
        :param obj: The object to be converted into a dictionary
        :return: A data-only dictionary that represents all the data for
                the given object, either in primitives
                (booleans, ints, floats, strings), arrays, or dictionaries.
                If obj is None, then the returned dictionary should also be
                None.  If obj is not the correct type, it is also reasonable
                to return None.
        """
        # At this point we are not going back to OpenAI functional specs
        raise NotImplementedError

    def from_dict(self, obj_dict: Dict[str, Any]) -> BaseModel:
        """
        :param obj_dict: The data-only dictionary to be converted into an object
        :return: An object instance created from the given dictionary.
                If obj_dict is None, the returned object should also be None.
                If obj_dict is not the correct type, it is also reasonable
                to return None.
        """
        base_model: BaseModel = self.openai_function_to_pydantic(self.top_level_field_name, obj_dict)
        return base_model

    def openai_function_to_pydantic(self, name: str, function_dict: Dict[str, Any]) -> BaseModel:
        """
        Turns an openai function spec dictionary into a pydantic BaseModel
        See: https://docs.pydantic.dev/latest/concepts/models/#dynamic-model-creation

        :param name: The string name of the object/field undergoing conversion
        :param function_dict: The dictionary describing the OpenAI function to
                    be converted into a pydantic BaseModel
        :return: The pydantic BaseModel that corresponds to the OpenAI function spec.
        """

        # Get stuff from the object-level function dictionary
        # from the OpenAI function spec
        properties: Dict[str, Any] = function_dict.get("properties", {})
        required: List[str] = []
        required = function_dict.get("required", required)

        fields: Dict[str, Any] = {}
        for field_name, one_property in properties.items():

            # Reject parameter names pydantic cannot make fields for
            # before they reach create_model() below.
            self.validate_field_name(field_name)

            # Get bits we need to assemble a pydantic Field description
            description: str = one_property.get("description")
            field_type: Type = self.get_type_from_property_dict(field_name, one_property)

            # Assemble a pydantic Field
            field_kwargs: Dict[str, Any] = {}

            # Description helps the agents communicate upstream what the field does
            if description is not None:
                field_kwargs["description"] = description

            # Setting a default to None is like saying that it's not required.
            # This allows agent infra to not include the field in the args
            # when a value is not there.  By contrast, we do not set a default
            # for something that is required, which leaves the pydantic definition
            # of "Undefined" in place which to agent infra implies a required arg.
            if field_name not in required:
                field_kwargs["default"] = None
                # Pydantic v1 implicitly made any field with a None default Optional.
                # Pydantic v2 does not, so wrap the type explicitly lest an LLM
                # passing an explicit null for an optional arg fail validation.
                field_type = Optional[field_type]
            field = Field(**field_kwargs)

            # Add the field to our dictionary with its name as key
            fields[field_name] = (field_type, field)

        # Create the pydantic BaseModel for the type dynamically
        try:
            model: BaseModel = create_model(name, **fields)
        except (NameError, TypeError) as exception:
            # Safety net for anything validate_field_name() does not cover:
            # report whatever create_model() rejects as the same spec-error
            # type the rest of the pipeline knows how to handle cleanly.
            raise ToolSpecError(f"Could not create pydantic model '{name}': {exception}") from exception
        return model

    def validate_field_name(self, field_name: str):
        """
        :param field_name: The string name of a single parameter/field.
                Raises ToolSpecError for parameter names that pydantic v2's
                create_model() cannot accept as field names.

        Pydantic v1 tolerated all of the names rejected here (it merely
        warned about and dropped underscore-prefixed names), but pydantic v2
        fails on them with cryptic NameError/TypeError at model-creation
        time.  The invalid names are:

        * Names with a leading underscore (e.g. "_internal", "__config__"):
          pydantic v2 reserves these for private attributes, and dunder
          names collide with create_model()'s own keyword arguments.
        * "model_config": silently consumed as create_model()'s model
          configuration argument instead of becoming a field.
        * Names that shadow a BaseModel method inside pydantic's protected
          namespaces "model_dump" and "model_validate" (e.g. "model_dump",
          "model_dump_json", "model_validate_json").  Other "model_"-prefixed
          names (e.g. "model_name") are fine.
        """
        message: str = None
        if field_name.startswith("_"):
            message = f"Parameter name '{field_name}' must not start with an underscore."
        elif field_name == "model_config":
            message = "Parameter name 'model_config' is reserved by pydantic for model configuration."
        elif field_name.startswith(("model_dump", "model_validate")) and hasattr(BaseModel, field_name):
            message = f"Parameter name '{field_name}' shadows a pydantic BaseModel method."

        if message is not None:
            raise ToolSpecError(message)

    def get_type_from_property_dict(self, field_name: str, one_property: Dict[str, Any]) -> Type:
        """
        :param field_name: The string name of the field undergoing conversion
        :param one_property: The property dictionary of the field whose type we are looking for.
        :return: the Type of the property to be used with pydantic Fields
                This type may be a BaseModel if object specification is
                deep enough.
        """
        type_from_dict: str = one_property.get("type")
        field_type: Type = self.TYPE_LOOKUP.get(type_from_dict)

        # Pydantic v1 rejected the None annotation that resulted from an
        # unrecognized type string, but pydantic v2 accepts None as NoneType,
        # so raise explicitly to keep bad specs from validating silently.
        if field_type is None:
            raise ToolSpecError(f"Unrecognized type '{type_from_dict}' for field '{field_name}'")

        if type_from_dict == "object":

            object_props: Dict[str, Any] = one_property.get("properties")
            if object_props is not None and object_props:
                # If the object has properties, make a new pydantic BaseModel for it
                # and include that as its type. This allows field descriptions,
                # and required-ness to be part of the object definition.
                field_type = self.openai_function_to_pydantic(field_name, one_property)

            # If there are no properties, we use the default in the TYPE_LOOKUP
            # which is Dict[str, Any]: the argument reaches the tool as a plain
            # dictionary and is advertised to the LLM provider as a real JSON
            # object type.  See the note on TYPE_LOOKUP above for why this is
            # deliberately not Any.

        elif type_from_dict == "array":

            # Get the type of the list components/items
            items: Dict[str, Any] = one_property.get("items")
            item_type: Type = self.get_type_from_property_dict(f"{field_name}_component", items)

            # Set the field_type as a properly typed generic List
            field_type = List[item_type]

        return field_type
