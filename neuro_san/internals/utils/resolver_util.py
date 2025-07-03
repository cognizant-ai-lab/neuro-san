# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT

from typing import Any
from typing import List
from typing import Type

from leaf_common.config.resolver import Resolver


class ResolverUtil:
    """
    Helper class for creating instances of classes that are referenced by a string.
    """

    @staticmethod
    def create_instance(class_name: str, class_name_source: str, type_of_class: Type) -> Any:
        """
        Resolves the class_name to instantiate an instance of the class.
        Goes through some standard checking with standard exceptions thrown
        to make sure the class is set up the way we want it.

        :param class_name: The fully qualified class name to instantiate
        :param class_name_source: A string description of where we are getting the value of
                    class_name, so that exceptions can be more instructive.
        :param type_of_class: The type that the instance must be in order to pass muster.
        :return: An instance of the class referred to by class_name if everything is successful.
                Can return None if class_name is a None or empty string.
        """

        instance: Any = None

        if class_name is None or len(class_name) == 0:
            return None

        # Split the single string into package, module, and class name
        class_split: List[str] = class_name.split(".")
        if len(class_split) <= 2:
            raise ValueError(f"Value from {class_name_source} '{class_name}' "
                             "must be of the form <package_name>.<module_name>.<ClassName>")

        packages: List[str] = [".".join(class_split[:-2])]
        class_name: str = class_split[-1]
        resolver = Resolver(packages)

        # Resolve the class name
        class_reference: Type[Any] = None
        try:
            class_reference = resolver.resolve_class_in_module(class_name, module_name=class_split[-2])
        except AttributeError:
            raise ValueError(f"Class '{class_name}' from {class_name_source} "
                             "not found in PYTHONPATH")

        # Instantiate the class
        try:
            instance = class_reference()
        except TypeError:
            raise ValueError(f"Class '{class_name}' from {class_name_source} "
                             "must have a no-args constructor")

        # Make sure it is the correct type
        if not isinstance(instance, type_of_class):
            raise ValueError(f"Class '{class_name}' from {class_name_source} "
                             "must be of type {type_of_class.__name__}")

        return instance
