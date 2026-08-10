
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
from typing import Type

from sys import modules
from warnings import warn

from leaf_common.config.resolver_util import ResolverUtil


class DeprecationRedirect:
    """
    Utilities for redirecting deprecated classes based on a single dictionary of the format:
        {
            "<old_class_name>": {
                "old_module": "<old_module_name>",
                "new_class": "<fully_qualified_new_class_name>",
            },
            ...
        }
    """

    def __init__(self, module_name: str, old_class_to_new_class: Dict[str, Dict[str, Any]]):
        """
        Constructor

        :param module_name: The name of module doing the redirecting
        :param old_class_to_new_class: Data dictionary described in the class comment
        """
        self.module_name: str = module_name
        self.old_class_to_new_class: Dict[str, Dict[str, Any]] = old_class_to_new_class
        self.redirect_modules()

    def redirect_modules(self):
        """
        Redirect deprecated classes and their modules
        """
        old_class: str = None
        old_class_dict: Dict[str, Any] = None
        for old_class, old_class_dict in self.old_class_to_new_class.items():
            old_module: str = old_class_dict.get("old_module")
            modules[f"{self.module_name}.{old_module}"] = modules[self.module_name]
            # Keep a boolean flag to warn only once
            old_class_dict["warned"] = False

    def redirect_class(self, old_class: str) -> Type[Any]:
        """
        Redirect deprecated classes

        :param old_class: The old class name
        """
        old_class_dict: Dict[str, str] = self.old_class_to_new_class.get(old_class)
        if old_class_dict is None:
            # The new class name is not in the map, so this is not a deprecated class but simply its own error
            raise AttributeError(f"module {self.module_name} has no attribute {old_class}")

        # The new class name is in the map, return the type with a warning
        new_class: str = old_class_dict.get("new_class")
        new_type: Type[Any] = ResolverUtil.create_type(new_class)

        # Only warn once
        if not old_class_dict.get("warned"):
            old_class_dict["warned"] = True

            # Emit the deprecation warning
            old_module: str = old_class_dict.get("old_module")
            full_ref: str = f"{self.module_name}.{old_module}.{old_class}"
            warn(f"{full_ref} is deprecated, use {new_class} instead.", DeprecationWarning, stacklevel=3)

        return new_type
