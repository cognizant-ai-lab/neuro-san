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


from typing import Any
from typing import Dict
from typing import List
from typing import Union


class SlyDataFlattener:
    """
    Collects every string-valued field of a sly_data tree for the report.

    Fields like ``reservation_id`` may be nested inside lists
    (``sly_data["agent_reservations"][0]["reservation_id"]``), so a flat
    top-level scan would miss them.  DictionaryExtractor from leaf-common is
    not used because it resolves one dotted key at a time and does not
    descend into lists.
    """

    @staticmethod
    def flatten_string_fields(sly_data: Dict[str, Any]) -> Dict[str, str]:
        """
        Collect every string-valued field at any depth of sly_data.

        :param sly_data: The sly_data dictionary returned by the agent
        :return: Field name to string value; the first occurrence of a name wins
        """
        parsed_fields: Dict[str, str] = {}
        SlyDataFlattener._collect(sly_data, parsed_fields)
        return parsed_fields

    @staticmethod
    def _collect(node: Union[Dict[str, Any], List[Any]], parsed_fields: Dict[str, str]) -> None:
        """
        Walk one dict or list node, filling parsed_fields in place.

        :param node: A dict or list somewhere inside sly_data
        :param parsed_fields: Field name to string value, filled in place
        """
        children: List[Any] = []
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str):
                    parsed_fields.setdefault(key, value)
                else:
                    children.append(value)
        elif isinstance(node, list):
            children = node
        for child in children:
            if isinstance(child, (dict, list)):
                SlyDataFlattener._collect(child, parsed_fields)
