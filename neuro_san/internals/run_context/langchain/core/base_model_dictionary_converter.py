
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
from typing import Type

from pydantic import BaseModel
from pydantic.v1 import Field
from pydantic.v1 import create_model

from leaf_common.serialization.interface.dictionary_converter import DictionaryConverter


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

        # Note: "Any" produces a pydantic BaseModel object whose fields
        #       are direct members when passed as an argument to a CodedTool
        #       or any other Tool.  If you really want a dictionary,
        #       you need to turn it into one using foo = dict(my_object_arg)
        #       See: https://docs.pydantic.dev/1.10/usage/exporting_models/#dictmodel-and-iteration
        #       This is what the PydanticArgumentDictionaryConverter is for.
        "object": Any
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
            field = Field(**field_kwargs)

            # Add the field to our dictionary with its name as key
            fields[field_name] = (field_type, field)

        # Create the pydantic BaseModel for the type dynamically
        model: BaseModel = create_model(name, **fields)
        return model

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

        if type_from_dict == "object":

            object_props: Dict[str, Any] = one_property.get("properties")
            if object_props is not None and object_props:
                # If the object has properties, make a new pydantic BaseModel for it
                # and include that as its type. This allows field descriptions,
                # and required-ness to be part of the object definition.
                field_type = self.openai_function_to_pydantic(field_name, one_property)

            # If there are no properties, we use the default in the TYPE_LOOKUP
            # which is Any.  Any passes a dynamically constructed pydantic object
            # whose fields can be accessed like regular fields.  This is nice
            # and fancy, but what we really want is a dictionary.

        elif type_from_dict == "array":

            # Get the type of the list components/items
            items: Dict[str, Any] = one_property.get("items")
            item_type: Type = self.get_type_from_property_dict(f"{field_name}_component", items)

            # Set the field_type as a properly typed generic List
            field_type = List[item_type]

        return field_type
