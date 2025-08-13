
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
from typing import Dict
from typing import Set
from typing import Type
from typing import Union
from types import MethodType
from inspect import isclass
from inspect import signature
from pydantic import BaseModel


class ArgumentValidator:
    """
    A utility class for inspecting method and class arguments, particularly useful for
    validating input against Pydantic `BaseModel` subclasses or callable method signatures.

    This class provides static methods to:
    - Validate that a dictionary of arguments matches the accepted parameters of a class or method.
    - Extract all field names and aliases from a Pydantic BaseModel subclass.
    """

    @staticmethod
    def check_invalid_args(method_class: Union[Type, MethodType], args: Dict[str, Any]):
        """
        Check for invalid arguments in a class constructor or method call.

        :param method_class: The class or method to validate against.
        :param args: Dictionary of argument to check.
        :raises ValueError: If any argument name is not accepted by the method or class.
        """

        # If method_class is a Pydantic BaseModel, get its field names and aliases
        if isclass(method_class) and issubclass(method_class, BaseModel):
            class_args_set: Set[str] = ArgumentValidator.get_base_model_args(method_class)
        else:
            # Otherwise, extract argument names from the function/method signature
            class_args_set = set(signature(method_class).parameters.keys())

        # Get the argument keys provided by the user
        args_set: Set[str] = set(args.keys())

        # Identify which arguments are not accepted by the method/class
        invalid_args: Set[str] = args_set - class_args_set
        if invalid_args:
            raise ValueError(
                f"Arguments {invalid_args} for '{method_class.__name__}' do not match any attributes "
                "of the class or any arguments of the method."
            )

    @staticmethod
    def get_base_model_args(base_model_class: Type[BaseModel]) -> Set[str]:
        """
        Extract all field names and aliases from a Pydantic BaseModel class.

        :param base_model_class: A class that inherits from `BaseModel`.
        :return: A set of valid argument names, including both field names and aliases.
        """

        fields_and_aliases: Set[str] = set()

        # Check for field name and info
        # field info includes attributes like "required", "default", "description", and "alias"
        for field_name, field_info in base_model_class.model_fields.items():
            # Add field name to the set
            fields_and_aliases.add(field_name)
            if field_info.alias:
                # If there is "alias" in the info add it to the set as well
                fields_and_aliases.add(field_info.alias)

        return fields_and_aliases
