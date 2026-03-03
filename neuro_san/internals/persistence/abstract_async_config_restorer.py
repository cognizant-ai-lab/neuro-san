
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

from io import StringIO
from json.decoder import JSONDecodeError
from os import environ

from aiofiles import open as async_open
from pyparsing.exceptions import ParseException
from pyparsing.exceptions import ParseSyntaxException

from leaf_common.config.config_filter import ConfigFilter
from leaf_common.persistence.interface.restorer import Restorer
from leaf_common.serialization.format.hocon_serialization_format import HoconSerializationFormat
from leaf_common.serialization.format.json_serialization_format import JsonSerializationFormat
from leaf_common.serialization.interface.serialization_format import SerializationFormat


class AbstractAsyncConfigRestorer(Restorer, ConfigFilter):
    """
    An abstract implementation of a config dictionary Restorer that allows sync or async
    restoration from a file.  The file may be from an explicit string or an environment variable.
    Files themselves may be of the following formats:
        * HOCON - Warning: include files can only be synchronously loaded during deserialization.
        * JSON
    Allows for optional processing of the dictionary read in from the file via filter_config().
    """

    def __init__(self, file_purpose: str, env_var: str = None, must_exist: bool = True):
        """
        Constructor

        :param file_purpose: A string description of the file to be restored.
        :param env_var: An optional environment variable name to get any file_reference from.
        :param must_exist: True if the file must exist, False otherwise
        """
        self.file_purpose: str = file_purpose
        self.env_var: str = env_var
        self.must_exist: bool = must_exist

    def get_file_path(self, file_reference: str = None) -> str:
        """
        :param file_reference: The file reference to use when restoring.
                Default is None, implying the file reference should be looked
                up by the environment variable for the instance.
        :return: the file path to use. Could still be None
        """
        file_path: str = file_reference
        if not file_path and self.env_var:
            file_path = environ.get(self.env_var)
        return file_path

    def restore(self, file_reference: str = None) -> Dict[str, Any]:
        """
        Synchronous restore from the given file reference.
        :param file_reference: The file reference to use when restoring.
                Default is None, implying the file reference is up to the
                implementation.
        :return: a dictionary
        """
        config: Dict[str, Any] = None

        file_path = self.get_file_path(file_reference)
        if not file_path:
            return config

        # Do a synchronous read of the file contents
        file_contents: str = None

        try:
            with open(file_path, "r", encoding="utf-8") as file_obj:
                file_contents = file_obj.read()
        except FileNotFoundError:
            if self.must_exist:
                raise
            return config

        config = self.deserialize_file_contents(file_path, file_contents)
        return config

    async def async_restore(self, file_reference: str = None) -> Dict[str, Any]:
        """
        Asynchronous restore from the given file reference.
        :param file_reference: The file reference to use when restoring.
                Default is None, implying the file reference is up to the
                implementation.
        :return: a dictionary
        """
        config: Dict[str, Any] = None

        file_path = self.get_file_path(file_reference)
        if not file_path:
            return config

        # Do an asynchronous read of the file contents
        file_contents: str = None
        try:
            async with async_open(file_path, "r", encoding="utf-8") as file_obj:
                file_contents = await file_obj.read()
        except FileNotFoundError:
            if self.must_exist:
                raise
            return config

        config = self.deserialize_file_contents(file_path, file_contents)
        return config

    def deserialize_file_contents(self, file_path: str, file_contents: str) -> Dict[str, Any]:
        """
        :param file_path: The path to the file being restored
        :param file_contents: The contents of the file
        :return: a dictionary
        """
        # Create a file-like object from the string
        string_file = StringIO(file_contents)

        # Determine the serialization format
        serialization: SerializationFormat = None
        if file_path.endswith(".hocon"):
            serialization = HoconSerializationFormat()
        else:
            serialization = JsonSerializationFormat()

        # Read the contents
        try:
            config = serialization.to_object(string_file)
        except (ParseException, ParseSyntaxException, JSONDecodeError) as exception:
            message: str = f"""
There was an error parsing {self.file_purpose} file "{file_path}".
See the accompanying exception (above) for clues as to what might be
syntactically incorrect in that file.
"""
            raise ParseException(message) from exception

        return self.filter_config(config)

    def filter_config(self, basis_config: Dict[str, Any], file_path: str = None) -> Dict[str, Any]:
        """
        Filters the given basis config.

        Ideally this would be a Pure Function in that it would not
        modify the caller's arguments so that the caller has a chance
        to decide whether to take any changes returned.

        :param basis_config: The config dictionary to act as the basis for filtering
        :param file_path: The path to the file being restored
        :return: A config dictionary, potentially modified as per the
                policy encapsulated by the implementation
        """
        _ = file_path
        # By default, do no filtering
        return basis_config
