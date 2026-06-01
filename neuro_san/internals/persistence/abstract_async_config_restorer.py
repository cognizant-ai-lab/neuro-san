
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

from io import BytesIO
from json.decoder import JSONDecodeError
from logging import getLogger
from logging import Logger
from os import environ

from aiofiles import open as async_open
from pyhocon import ConfigException
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

    def __init__(self, file_purpose: str, env_var: str = None, must_exist: bool = True, deprecated_env_var: str = None):
        """
        Constructor

        :param file_purpose: A string description of the file to be restored.
        :param env_var: An optional environment variable name to get any file_reference from.
        :param deprecated_env_var: An optional environment variable name to get any file_reference from
                                   that is deprecated.
        :param must_exist: True if the file must exist, False otherwise
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.file_purpose: str = file_purpose
        self.env_var: str = env_var
        self.deprecated_env_var: str = deprecated_env_var
        self.must_exist: bool = must_exist

    def get_file_path(self, file_reference: str = None) -> str:
        """
        :param file_reference: The file reference to use when restoring.
                Default is None, implying the file reference should be looked
                up by the environment variable for the instance.
        :return: the file path to use. Could still be None
        """
        file_path: str = file_reference
        if (file_path is None or len(file_path) == 0) and self.env_var:

            # Get the value from the env var
            file_path = environ.get(self.env_var)
            if (file_path is None or len(file_path) == 0) and self.deprecated_env_var:

                # Get the value from the deprecated env var if there is one.
                file_path = environ.get(self.deprecated_env_var)
                if file_path is not None:
                    # Provide warning if the deprecated env var is set.
                    self.logger.warning("Using deprecated env var %s for %s. Please use %s instead.",
                                        self.deprecated_env_var, self.file_purpose, self.env_var)

        return file_path

    def restore(self, file_reference: str = None) -> Any:
        """
        Synchronous restore from the given file reference.
        :param file_reference: The file reference to use when restoring.
                Default is None, implying the file reference is up to the
                implementation.
        :return: a dictionary. Note the return type is Any so subclasses can
                override by returning an object. Without this, you get a dictionary.
        """
        config: Dict[str, Any] = None

        file_path = self.get_file_path(file_reference)
        if not file_path:
            return config

        # Do a synchronous read of the file contents
        file_contents: bytes = None

        try:
            with open(file_path, "rb") as file_obj:
                file_contents = file_obj.read()
        except FileNotFoundError:
            # Swallow this in favor of common exception verbiage in filter_config()
            pass

        if file_contents is not None:
            config = self.deserialize_file_contents(file_path, file_contents)

        return self.filter_config(config, file_path)

    async def async_restore(self, file_reference: str = None) -> Any:
        """
        Asynchronous restore from the given file reference.
        :param file_reference: The file reference to use when restoring.
                Default is None, implying the file reference is up to the
                implementation.
        :return: a dictionary. Note the return type is Any so subclasses can
                override by returning an object. Without this, you get a dictionary.
        """
        config: Dict[str, Any] = None

        file_path = self.get_file_path(file_reference)
        if not file_path:
            return config

        # Do an asynchronous read of the file contents
        file_contents: bytes = None
        try:
            async with async_open(file_path, "rb") as file_obj:
                file_contents = await file_obj.read()
        except FileNotFoundError:
            # Swallow this in favor of common exception verbiage in filter_config()
            pass

        if file_contents is not None:
            config = self.deserialize_file_contents(file_path, file_contents)

        return self.filter_config(config, file_path)

    def deserialize_file_contents(self, file_path: str, file_contents: bytes) -> Dict[str, Any]:
        """
        :param file_path: The path to the file being restored
        :param file_contents: The contents of the file as bytes
        :return: a dictionary
        """
        # Create a file-like object from the input bytes.
        # This allows us to use the same deserialization code for both sync and async reads.
        bytes_file = BytesIO(file_contents)

        # Determine the serialization format
        serialization: SerializationFormat = None
        if file_path.endswith(".hocon"):
            # Worth noting that includes within hocon files can only be done synchronously
            # The core pyhocon library does not support async includes.
            serialization = HoconSerializationFormat()
        elif file_path.endswith(".json"):
            serialization = JsonSerializationFormat()
        else:
            raise ValueError(f"File reference {file_path} must be a .json or .hocon file")

        # Read the contents
        try:
            config = serialization.to_object(bytes_file)
        except (ParseException, ParseSyntaxException, JSONDecodeError, ConfigException) as exception:
            # Re-raise as ValueError, not pyparsing.ParseException, for two reasons:
            #
            # 1. Not all caught errors are parse errors. ConfigException covers post-parse
            #    failures like ConfigSubstitutionException (unresolved ${VAR} references)
            #    and ConfigMissingException — re-raising those as a "parse exception" is
            #    semantically misleading.
            #
            # 2. pyparsing.ParseBaseException.__str__ unconditionally appends
            #    "  (at char {loc}), (line:{lineno}, col:{col})" to its string form.
            #    For a wrapper exception that has no real source location, this prints
            #    "(at char 0), (line:1, col:1)" regardless of where the actual error is,
            #    which actively misleads anyone reading the log. There is no way to
            #    suppress that suffix without subclassing ParseException and overriding
            #    __str__; using ValueError sidesteps the problem entirely.
            #
            # We embed the underlying exception's type and message directly in the wrapper
            # text so the real cause surfaces via str(e). Without this, callers that log
            # "%s" % e see only the wrapper and lose the root cause — `from exception`
            # only attaches the original via __cause__, which is rendered in tracebacks
            # but not in str().
            message: str = (
                f'There was an error loading {self.file_purpose} file "{file_path}".\n'
                f"Underlying error ({type(exception).__name__}): {exception}"
            )
            raise ValueError(message) from exception

        return config

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
        if basis_config is None and self.must_exist:

            env_var_msg: str = ""
            if self.env_var:
                if not self.deprecated_env_var:
                    env_var_msg = f" the value of the {self.env_var} env var and"
                else:
                    env_var_msg = f" the value of the {self.env_var} and/or the deprecated " + \
                                  f"{self.deprecated_env_var} env vars and"

            message = f"""
Could not find {self.file_purpose} file at path: {file_path}.
Some common problems include:
    * The file itself simply does not exist.
    * Path is not an absolute path and you are invoking the server from a place
      where the path is not reachable.
    * The path has a typo in it.

Double-check{env_var_msg} your current working directory (pwd).
"""
            raise FileNotFoundError(message)

        # By default, do no filtering
        return basis_config
