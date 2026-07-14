
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

from json import dumps
from objsize import get_deep_size


class MemoryUtil:
    """
    Utility methods for examining memory of an object.
    """

    @staticmethod
    def get_memory_dict(obj_in: Any) -> Dict[str, Any]:
        """
        Get the memory usage of an object.

        :param object: The object to get the memory usage of.
        :return: A dictionary of the memory usage of the object.
        """
        usage: Dict[str, int] = {}
        usage["self"] = get_deep_size(obj_in)
        if obj_in is not None:
            usage["type"] = type(obj_in).__name__
            for key, value in vars(obj_in).items():

                member_size: int = 0
                try:
                    member_size = get_deep_size(value)
                except Exception:  # pylint: disable=broad-except
                    # Ignore exceptions - these would come from methods as vars and other squirrely bits
                    pass

                if member_size > 0:
                    member_type: str = "Unknown"
                    try:
                        member_type = type(value).__name__
                    except Exception:  # pylint: disable=broad-except
                        # Ignore exceptions - these would come from methods as vars and other squirrely bits
                        pass

                    usage[key] = {
                        "type": member_type,
                        "size": member_size
                    }
                else:
                    usage[key] = member_size
        return usage

    @staticmethod
    def get_pretty_memory_dict(obj_in: Any) -> str:
        """
        Get a string representation of the memory usage of an object.

        :param object: The object to get the memory usage of.
        :return: A string representation of the memory usage of the object.
        """
        mem_dict: Dict[str, Any] = MemoryUtil.get_memory_dict(obj_in)
        mem_str: str = dumps(mem_dict, indent=4, sort_keys=True)
        return mem_str
