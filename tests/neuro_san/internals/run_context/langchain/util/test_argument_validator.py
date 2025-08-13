
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

from pydantic import BaseModel
from pydantic import Field
import pytest

from neuro_san.internals.run_context.langchain.util.argument_validator import ArgumentValidator


# ----------- Sample Models and Functions for Testing -----------

class SampleModel(BaseModel):
    """Used for get_base_model_args method testing"""
    name: str
    age: int = Field(alias="years")


def sample_function(name: str, city: str):
    """Used for method signature testing"""
    print(name, city)


# ------------------------- Tests -------------------------------

class TestArgumentValidator:
    """Tests for the ArgumentValidator class and its static validation utilities."""

    def test_get_base_model_args_returns_field_names_and_aliases(self):
        """
        Test that get_base_model_args returns both the original field names
        and their aliases from a Pydantic BaseModel.
        """
        result: Set[str] = ArgumentValidator.get_base_model_args(SampleModel)
        # Expect both the field name 'name' and the alias 'years' to be included
        assert "name" in result
        assert "years" in result
        assert "age" in result  # The original field name is also always included

    def test_check_invalid_args_with_valid_model_args_passes(self):
        """
        Test that check_invalid_args does not raise an error when passed
        valid field names and aliases for a BaseModel.
        """
        args: Dict[str, Any] = {"name": "Alice", "years": 30}
        # Should not raise
        ArgumentValidator.check_invalid_args(SampleModel, args)

    def test_check_invalid_args_with_invalid_model_args_raises(self):
        """
        Test that check_invalid_args raises a ValueError when invalid field names
        are passed to a BaseModel.
        """
        args: Dict[str, Any] = {"name": "Alice", "invalid_field": "oops"}
        with pytest.raises(ValueError) as excinfo:
            ArgumentValidator.check_invalid_args(SampleModel, args)
        assert "invalid_field" in str(excinfo.value)

    def test_check_invalid_args_with_valid_function_args_passes(self):
        """
        Test that check_invalid_args does not raise an error when valid argument
        names are passed to a regular Python function.
        """
        args: Dict[str, Any] = {"name": "Alice", "city": "NYC"}
        # Should not raise
        ArgumentValidator.check_invalid_args(sample_function, args)

    def test_check_invalid_args_with_invalid_function_args_raises(self):
        """
        Test that check_invalid_args raises a ValueError when invalid argument
        names are passed to a regular Python function.
        """
        args: Dict[str, Any] = {"name": "Alice", "bad_arg": "fail"}
        with pytest.raises(ValueError) as excinfo:
            ArgumentValidator.check_invalid_args(sample_function, args)
        assert "bad_arg" in str(excinfo.value)
