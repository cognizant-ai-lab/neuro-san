
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

from neuro_san import TOP_LEVEL_DIR
from neuro_san.internals.persistence.abstract_async_config_restorer import AbstractAsyncConfigRestorer


class LlmInfoRestorer(AbstractAsyncConfigRestorer):
    """
    Implementation of the AbstractAsyncConfigRestorer interface to read in an LlmInfo dictionary
    instance given a hocon file name.
    The restore() and async_restore() methods both return dictionary instances.
    """

    def __init__(self):
        """
        Constructor
        """
        super().__init__(file_purpose="llm_info")

    def get_file_path(self, file_reference: str = None) -> str:
        """
        :param file_reference: The file reference to use when restoring.
                Default is None, implying the file reference is up to the
                implementation.
        :return: a string representing the file path to use
        """
        use_file: str = file_reference

        if file_reference is None or len(file_reference) == 0:
            # Read from the default
            use_file = TOP_LEVEL_DIR.get_file_in_basis("internals/run_context/langchain/llms/default_llm_info.hocon")

        return use_file
