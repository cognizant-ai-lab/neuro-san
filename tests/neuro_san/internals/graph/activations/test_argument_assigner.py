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

from unittest import TestCase

from neuro_san.internals.graph.activations.argument_assigner import ArgumentAssigner


class TestArgumentAssigner(TestCase):
    """Unit tests for ArgumentAssigner class"""

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.properties = {
            "name": {"type": "string"},
            "age": {"type": "int"},
            "scores": {"type": "array"},
            "metadata": {"type": "object"},
            "active": {"type": "boolean"}
        }
        self.assigner = ArgumentAssigner(self.properties)

    def test_assign_string_argument(self):
        """Test assigning string argument"""
        arguments = {"name": "John Doe"}
        result = self.assigner.assign(arguments)
        expected = ["The name is 'John Doe'."]
        self.assertEqual(result, expected)

    def test_assign_integer_argument(self):
        """Test assigning integer argument"""
        arguments = {"age": 25}
        result = self.assigner.assign(arguments)
        expected = ["The age is 25."]
        self.assertEqual(result, expected)

    def test_assign_array_argument(self):
        """Test assigning array argument"""
        arguments = {"scores": [85, 92, 78]}
        result = self.assigner.assign(arguments)
        expected = ["The scores are 85, 92, 78."]
        self.assertEqual(result, expected)

    def test_assign_dict_argument(self):
        """Test assigning dict argument"""
        arguments = {"metadata": {"key1": "value1", "key2": "value2"}}
        result = self.assigner.assign(arguments)
        expected = ['The metadata is "key1": "value1", "key2": "value2".']
        self.assertEqual(result, expected)

    def test_assign_boolean_argument(self):
        """Test assigning boolean argument"""
        arguments = {"active": True}
        result = self.assigner.assign(arguments)
        expected = ["The active is True."]
        self.assertEqual(result, expected)

    def test_assign_multiple_arguments(self):
        """Test assigning multiple arguments"""
        arguments = {
            "name": "Alice",
            "age": 30,
            "scores": [95, 87]
        }
        result = self.assigner.assign(arguments)
        self.assertEqual(len(result), 3)
        self.assertIn("The name is 'Alice'.", result)
        self.assertIn("The age is 30.", result)
        self.assertIn("The scores are 95, 87.", result)

    def test_assign_with_none_values(self):
        """Test that None values are skipped"""
        arguments = {
            "name": "Bob",
            "age": None,
            "scores": [100, 95]
        }
        result = self.assigner.assign(arguments)
        self.assertEqual(len(result), 2)
        # age should be skipped due to None value
        self.assertNotIn("age", " ".join(result))

    def test_assign_with_unknown_property(self):
        """Test that unknown properties are skipped"""
        arguments = {
            "name": "Charlie",
            "unknown_field": "should be skipped"
        }
        result = self.assigner.assign(arguments)
        expected = ["The name is 'Charlie'."]
        self.assertEqual(result, expected)

    def test_assign_with_no_properties(self):
        """Test assignment when no properties are defined"""
        assigner = ArgumentAssigner(None)
        arguments = {"field": "value"}
        result = assigner.assign(arguments)
        expected = ["The field is value."]
        self.assertEqual(result, expected)

    def test_get_args_value_as_string_with_string_type(self):
        """Test string value conversion with explicit string type"""
        result = self.assigner.get_args_value_as_string("test value", "string")
        expected = "'test value'"
        self.assertEqual(result, expected)

    def test_get_args_value_as_string_with_curly_braces(self):
        """Test string value conversion with curly braces"""
        result = self.assigner.get_args_value_as_string("value with {braces}", "string")
        expected = "'value with {{braces}}'"
        self.assertEqual(result, expected)

    def test_get_args_value_as_string_with_dict_type(self):
        """Test dict value conversion"""
        test_dict = {"key": "value", "number": 42}
        result = self.assigner.get_args_value_as_string(test_dict, "dict")
        # Should strip outer braces
        self.assertTrue(result.startswith('"key"'))
        self.assertTrue(result.endswith('42'))
        self.assertNotIn('{', result[0])
        self.assertNotIn('}', result[-1])

    def test_get_args_value_as_string_with_array_type(self):
        """Test array value conversion"""
        test_array = ["item1", "item2", 123]
        result = self.assigner.get_args_value_as_string(test_array, "array")
        expected = "item1, item2, 123"
        self.assertEqual(result, expected)

    def test_get_args_value_as_string_with_nested_array(self):
        """Test nested array value conversion"""
        test_array = [["nested", "array"], "simple"]
        result = self.assigner.get_args_value_as_string(test_array, "array")
        expected = "nested, array, simple"
        self.assertEqual(result, expected)

    def test_get_args_value_as_string_default_case(self):
        """Test default string conversion for other types"""
        result = self.assigner.get_args_value_as_string(42.5)
        expected = "42.5"
        self.assertEqual(result, expected)

    def test_get_args_value_as_string_with_none_value_type(self):
        """Test string conversion with None value_type"""
        result = self.assigner.get_args_value_as_string("test", None)
        expected = "test"
        self.assertEqual(result, expected)

    def test_assignment_verb_singular(self):
        """Test that singular arguments use 'is' verb"""
        arguments = {"name": "Test"}
        result = self.assigner.assign(arguments)
        self.assertIn("is", result[0])

    def test_assignment_verb_plural_array_type(self):
        """Test that array type arguments use 'are' verb"""
        arguments = {"scores": [1, 2, 3]}
        result = self.assigner.assign(arguments)
        self.assertIn("are", result[0])

    def test_empty_arguments(self):
        """Test with empty arguments dictionary"""
        arguments = {}
        result = self.assigner.assign(arguments)
        self.assertEqual(result, [])
