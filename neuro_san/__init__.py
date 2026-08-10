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
from typing import Type

from leaf_common.config.file_of_class import FileOfClass

from neuro_san.internals.utils.deprecation_redirect import DeprecationRedirect

# Normally we don't use __init__.py files to define anything,
# but here we define some constants that point to important directories in the distribution.
TOP_LEVEL_DIR = FileOfClass(__file__)
DEPLOY_DIR = FileOfClass(__file__, path_to_basis="./deploy")
REGISTRIES_DIR = FileOfClass(__file__, path_to_basis="./registries")


_DEPRECATION_REDIRECT = DeprecationRedirect(
    __name__,
    # A map from old class name to new class name for compatibility
    {
        "neuro_san.internals.messages.chat_message_type.ChatMessageType":
            "neuro_san.message.types.chat_message_type.ChatMessageType",
        "neuro_san.internals.messages.origination.Origination":
            "neuro_san.internals.journals.origination.Origination",
        "neuro_san.internals.parsers.structure.json_structure_parser.JsonStructureParser":
            "neuro_san.message.parsers.structure.json_structure_parser.JsonStructureParser",
        "neuro_san.message_processors.message_processor.MessageProcessor":
            "neuro_san.message.processors.message_processor.MessageProcessor",
        "neuro_san.message_processors.basic_message_processor.BasicMessageProcessor":
            "neuro_san.message.processors.basic_message_processor.BasicMessageProcessor",
    },
    next_version="0.7.0"
)


def __getattr__(old_class: str) -> Type[Any]:
    """
    Redirect deprecated classes
    :param old_class: The old class name
    :return: The redirected class
    """
    return _DEPRECATION_REDIRECT.redirect_class(old_class)
