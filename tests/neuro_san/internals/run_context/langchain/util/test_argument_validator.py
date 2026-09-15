
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

from unittest import TestCase
import pytest

from pydantic import BaseModel
from pydantic import Field


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

class TestArgumentValidator(TestCase):
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
