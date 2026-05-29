
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

from pydantic import BaseModel

from leaf_common.serialization.interface.dictionary_converter import DictionaryConverter


class PydanticArgumentDictionaryConverter(DictionaryConverter):
    """
    DictionaryConverter implementation which can convert a
    dynamically created pydantic object to a dictionary for use
    in passing arguments around.
    """

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
        # Do the pydantic conversion to a dict
        base_dict: Dict[str, Any] = dict(obj)

        # Loop through all the keys, recursively converting any sub-objects
        # (dicts, pydantic objects, and list elements thereof) to dictionaries.
        new_dict: Dict[str, Any] = {}
        for key, value in base_dict.items():
            new_dict[key] = self._convert_value(value)

        return new_dict

    def _convert_value(self, value: Any) -> Any:
        """
        Recursively convert a single value, descending into dicts, pydantic
        BaseModel instances, and lists thereof.
        """
        if isinstance(value, Dict) or self.is_pydantic_object(value):
            return self.to_dict(value)
        if isinstance(value, list):
            converted_list: List = []
            for item in value:
                converted_list.append(self._convert_value(item))
            return converted_list
        return value

    def from_dict(self, obj_dict: Dict[str, Any]) -> BaseModel:
        """
        :param obj_dict: The data-only dictionary to be converted into an object
        :return: An object instance created from the given dictionary.
                If obj_dict is None, the returned object should also be None.
                If obj_dict is not the correct type, it is also reasonable
                to return None.
        """
        # At this point we are not going back to BaseModel objects
        raise NotImplementedError

    def is_pydantic_object(self, value: Any) -> bool:
        """
        :param value: the value to test
        :return: True if the object is a pydantic object. False otherwise.
        """
        return hasattr(value, "parse_obj") and callable(value.parse_obj)
