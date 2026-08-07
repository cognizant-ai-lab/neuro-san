
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

import pytest

from pydantic import BaseModel

from neuro_san.internals.run_context.langchain.core.langchain_openai_function_tool \
    import LangChainOpenAIFunctionTool
from neuro_san.internals.run_context.langchain.core.tool_spec_error import ToolSpecError


class TestLangChainOpenAIFunctionTool:
    """
    Test cases for creating tools from OpenAI function specs.
    """

    def test_missing_parameters_builds_explicit_empty_args_schema(self):
        """
        A spec with no parameters block still gets an explicit (empty)
        args_schema.  Leaving args_schema unset would let langchain derive
        a schema from _arun(*args, **kwargs), which emits an "args" array
        property without "items" that Gemini rejects.
        """
        function_json = {"name": "ext_agent", "description": "d"}
        tool = LangChainOpenAIFunctionTool.from_function_json(function_json, None)
        assert tool.args_schema is not None
        assert issubclass(tool.args_schema, BaseModel)

    def test_explicit_null_parameters_builds_explicit_empty_args_schema(self):
        """
        An explicit "parameters": null - expressible in the JSON specs
        external agents send over the network - is normalized to the same
        explicit empty args_schema as a missing parameters block, now that
        the converter honors the DictionaryConverter None -> None contract.
        """
        function_json = {"name": "ext_agent", "description": "d", "parameters": None}
        tool = LangChainOpenAIFunctionTool.from_function_json(function_json, None)
        assert tool.args_schema is not None
        assert issubclass(tool.args_schema, BaseModel)

    def test_non_dict_parameters_raises_tool_spec_error(self):
        """
        A truthy non-dict "parameters" value follows the invalid-spec error
        path instead of raising a raw AttributeError from parameters.get().
        """
        function_json = {"name": "ext_agent", "description": "d", "parameters": "not-a-dict"}
        with pytest.raises(ToolSpecError, match="'parameters' to be a dictionary"):
            LangChainOpenAIFunctionTool.from_function_json(function_json, None)
