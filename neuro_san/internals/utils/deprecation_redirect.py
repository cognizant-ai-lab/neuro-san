
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
from typing import Set
from typing import Type

from sys import modules
from warnings import warn

from leaf_common.config.resolver import Resolver
from leaf_common.config.resolver_util import ResolverUtil


class DeprecationRedirect:
    """
    Utilities for redirecting deprecated classes based on a single dictionary of the format:
        {
            "<fully_qualified_old_class_name>": "<fully_qualified_new_class_name>",
            ...
        }
    The idea is that one global instance of this class lives in a module's __init__.py file
    and is initialized with a dictionary described above and manages class redirections and
    deprecation warnings from there.
    """

    def __init__(self, module_name: str, old_class_to_new_class: Dict[str, str], next_version: str = None,
                 do_not_redirect_modules_for_testing: bool = False):
        """
        Constructor

        :param module_name: The name of module doing the redirecting
        :param old_class_to_new_class: Data dictionary described in the class comment
        :param next_version: The next version where the deprecation will be removed
        :param do_not_redirect_modules_for_testing: If true, do not redirect deprecated modules
        """
        self.module_name: str = module_name
        self.old_class_to_new_class: Dict[str, str] = old_class_to_new_class
        self.next_version: str = next_version
        self.do_not_redirect_modules_for_testing: bool = do_not_redirect_modules_for_testing

        self.warned: Set[str] = set()

        self.clean_keys()
        if not self.do_not_redirect_modules_for_testing:
            self.redirect_modules()

    def clean_keys(self):
        """
        Remove the module name from the keys
        """
        new_dict: Dict[str, str] = {}
        key: str = None
        existing_value: str = None
        for key, existing_value in self.old_class_to_new_class.items():
            if not key.startswith(f"{self.module_name}."):
                # The key class referenced is not based in this module. Leave it alone.
                new_dict[key] = existing_value
                continue

            new_key: str = key.removeprefix(f"{self.module_name}.")
            new_dict[new_key] = existing_value

        self.old_class_to_new_class = new_dict

    def redirect_modules(self):
        """
        Redirect deprecated classes and their modules
        """
        resolver = Resolver()
        old_class: str = None
        for old_class in self.old_class_to_new_class.keys():
            use_class: str = old_class
            while "." in use_class:
                old_module: str = self.get_module_from_fully_qualified(use_class)
                module_found = resolver.resolve_class_in_module(module_name=old_module, raise_if_not_found=False)
                if module_found:
                    # Don't need to replace something that already exists
                    break
                modules[f"{self.module_name}.{old_module}"] = modules[self.module_name]
                use_class = old_module

    def redirect_class(self, old_class: str) -> Type[Any]:
        """
        Redirect deprecated classes

        :param old_class: The old class name
        """
        fully_qualified_old_class: str = self.find_old_class_key(old_class)
        if fully_qualified_old_class is None:
            # The new class name is not in the map, so this is not a deprecated class but simply its own error
            raise AttributeError(f"module {self.module_name} has no attribute {old_class}")

        # The new class name is in the map, return the type with a warning
        new_class: str = self.old_class_to_new_class.get(fully_qualified_old_class)
        new_type: Type[Any] = ResolverUtil.create_type(new_class)

        if old_class not in self.warned:
            # Only warn once
            self.warned.add(old_class)

            # Emit the deprecation warning
            old_module: str = self.get_module_from_fully_qualified(fully_qualified_old_class)
            full_ref: str = f"{self.module_name}.{old_module}.{old_class}"
            warn(f"{full_ref} is deprecated and will be removed in version {self.next_version} or greater, "
                 f"use {new_class} instead.", DeprecationWarning, stacklevel=3)

        return new_type

    def find_old_class_key(self, old_class: str) -> str:
        """
        Find the old class key
        :param old_class: The old class name without the module
        :return: The old class key with the module
        """
        ends_with: str = f".{old_class}"
        for key in self.old_class_to_new_class.keys():
            if key.endswith(ends_with):
                return key
        return None

    @staticmethod
    def get_class_from_fully_qualified(fully_qualified_class: str) -> str:
        """
        Get the class name from the fully qualified class name
        :param fully_qualified_class: The fully qualified class name
        :return: The class name only
        """
        if fully_qualified_class is None:
            return None
        return fully_qualified_class.split(".")[-1]

    @staticmethod
    def get_module_from_fully_qualified(fully_qualified_class: str) -> str:
        """
        Get the module name from the fully qualified class name
        :param fully_qualified_class: The fully qualified class name
        :return: The module name only
        """
        if fully_qualified_class is None:
            return None

        return ".".join(fully_qualified_class.split(".")[:-1])
