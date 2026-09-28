
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
from typing import Optional

from json import load
from unittest import TestCase

from neuro_san import TOP_LEVEL_DIR
from neuro_san.service.mcp.validation.tool_request_validator import ToolRequestValidator


class TestToolRequestValidator(TestCase):
    """
    Tests for ToolRequestValidator, which derives the MCP tool-call input schema
    from the service OpenAPI spec (agent_service.json) and validates tool-call
    requests against it. The spec is loaded from the package the way
    ServerMainLoop loads it, so these tests also lock what a regenerated spec
    advertises for ChatMessage, including the content_blocks field.
    """

    # Same path ServerMainLoop uses for the default spec, relative to the package.
    SPEC_PATH: str = "api/grpc/agent_service.json"

    # The components a ChatRequest can reach; the validator prunes every other one.
    CHAT_REQUEST_COMPONENTS: List[str] = [
        "ChatContext", "ChatFilter", "ChatHistory", "ChatMessage", "ChatRequest", "MimeData", "Origin",
    ]

    @staticmethod
    def make_validator() -> ToolRequestValidator:
        """
        :return: A ToolRequestValidator over the packaged service spec.
        """
        spec_path: str = TOP_LEVEL_DIR.get_file_in_basis(TestToolRequestValidator.SPEC_PATH)
        with open(spec_path, "r", encoding="utf-8") as spec_file:
            spec: Dict[str, Any] = load(spec_file)
        return ToolRequestValidator(spec)

    def test_request_schema_is_rooted_at_a_strict_chat_request(self) -> None:
        """
        The derived schema is rooted at ChatRequest, keeps only the components a
        ChatRequest can reach, requires user_message and forbids unknown keys at
        the root.
        """
        validator: ToolRequestValidator = self.make_validator()
        schema: Dict[str, Any] = validator.get_request_schema()

        self.assertEqual(schema.get("$ref"), "#/components/schemas/ChatRequest")
        self.assertEqual(sorted(schema["components"]["schemas"]), self.CHAT_REQUEST_COMPONENTS)
        chat_request: Dict[str, Any] = schema["components"]["schemas"]["ChatRequest"]
        self.assertEqual(chat_request.get("required"), ["user_message"])
        self.assertIs(chat_request.get("additionalProperties"), False)

    def test_chat_message_advertises_content_blocks(self) -> None:
        """
        ChatMessage advertises content_blocks as an array of free-form objects,
        which is how the repeated google.protobuf.Struct field in chat.proto
        renders in the generated spec.
        """
        validator: ToolRequestValidator = self.make_validator()
        schema: Dict[str, Any] = validator.get_request_schema()
        content_blocks: Dict[str, Any] = schema["components"]["schemas"]["ChatMessage"]["properties"]["content_blocks"]

        self.assertEqual(content_blocks.get("type"), "array")
        self.assertEqual(content_blocks.get("items"), {"type": "object"})
        self.assertIn("LangChain v1 standard content blocks", content_blocks.get("description", ""))

    def test_text_only_request_validates(self) -> None:
        """
        A plain text request, the shape every existing client sends, validates.
        """
        validator: ToolRequestValidator = self.make_validator()
        errors: Optional[List[str]] = validator.validate({"user_message": {"type": "HUMAN", "text": "hello"}})
        self.assertIsNone(errors)

    def test_request_with_content_blocks_validates(self) -> None:
        """
        A request whose user_message carries a list of block dicts validates.
        """
        validator: ToolRequestValidator = self.make_validator()
        request: Dict[str, Any] = {
            "user_message": {
                "type": "HUMAN",
                "text": "hello",
                "content_blocks": [{"type": "text", "text": "hello"}],
            },
        }
        errors: Optional[List[str]] = validator.validate(request)
        self.assertIsNone(errors)

    def test_content_blocks_must_be_a_list_of_objects(self) -> None:
        """
        content_blocks that is not a list, or whose items are not objects, is
        rejected with the validator's single summary error.
        """
        validator: ToolRequestValidator = self.make_validator()

        not_a_list: Optional[List[str]] = validator.validate({"user_message": {"text": "hello", "content_blocks": 42}})
        self.assertEqual(len(not_a_list), 1)
        self.assertIn("Request validation FAILED", not_a_list[0])

        not_objects: Optional[List[str]] = validator.validate(
            {"user_message": {"text": "hello", "content_blocks": ["oops"]}})
        self.assertEqual(len(not_objects), 1)
        self.assertIn("Request validation FAILED", not_objects[0])
