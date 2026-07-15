
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

import hashlib
import os
import re
import threading
from collections import OrderedDict
from copy import deepcopy
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


# Regex to find local HOCON `include` directives and capture the quoted path.
# Handles: include "x", include required("x"), include file("x").
# url()/classpath()/package() forms may also match here but are harmlessly
# ignored later when the captured path does not resolve to a local file.
_HOCON_INCLUDE_PATTERN = re.compile(rb'include\s+(?:required\s*\(\s*)?(?:file\s*\(\s*)?"([^"]+)"')

# Environment variable that opts a process in to the deserialization cache.
# The cache is OFF by default so production/deployed servers are unaffected;
# it is intended for local development (e.g. neuro-san-studio) where the same
# HOCON files are parsed repeatedly on startup and on every file-change reload.
# Enable by setting the variable to one of: "1", "true", "yes", "on" (any case).
_CACHE_ENV_VAR = "NEURO_SAN_PARSE_CACHE"
_CACHE_TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})

# Upper bound on the number of distinct (file_path, content_hash) entries kept.
# Each edit to a watched file adds a new entry (the old content's entry is never
# reused), so a long dev session with many edit/reload cycles needs an eviction
# policy to avoid unbounded growth. Least-recently-used entries are evicted first.
_CACHE_MAX_ENTRIES = 256


class AbstractAsyncConfigRestorer(Restorer, ConfigFilter):
    """
    An abstract implementation of a config dictionary Restorer that allows sync or async
    restoration from a file.  The file may be from an explicit string or an environment variable.
    Files themselves may be of the following formats:
        * HOCON - Warning: include files can only be synchronously loaded during deserialization.
        * JSON
    Allows for optional processing of the dictionary read in from the file via filter_config().
    """

    # Class-level cache for deserialized file contents to avoid re-parsing the same files.
    # Gated by the _CACHE_ENV_VAR environment variable; empty and unused unless opted in.
    # An OrderedDict so we can evict least-recently-used entries once _CACHE_MAX_ENTRIES
    # is exceeded (see is_cache_enabled()/deserialize_file_contents()).
    _deserialization_cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    _cache_lock = threading.Lock()

    @staticmethod
    def is_cache_enabled() -> bool:
        """
        :return: True if the deserialization cache is opted in via the
                _CACHE_ENV_VAR environment variable, False otherwise.
                Evaluated per call so the setting can be toggled at runtime
                and so production processes (which never set it) pay nothing.
        """
        return environ.get(_CACHE_ENV_VAR, "").strip().lower() in _CACHE_TRUTHY_VALUES

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
        # The cache is opt-in (see _CACHE_ENV_VAR). When disabled we skip the
        # cache lookup AND the include-aware hashing (which itself reads the
        # included files), so production behavior and cost are unchanged.
        cache_enabled: bool = self.is_cache_enabled()
        cache_key: str = None
        if cache_enabled:
            # Create cache key from file path and an include-aware content hash.
            # The hash folds in the contents of every file this one transitively
            # includes, so editing a shared included file (e.g. aaosa.hocon or
            # llm_config.hocon) invalidates the cache entry of every dependent file.
            content_hash = self.compute_include_aware_hash(file_path, file_contents)
            cache_key = f"{file_path}:{content_hash}"

            # Check cache first (thread-safe).
            # Return a deepcopy, not the cached object itself: callers (e.g. filter_config
            # chains) are not guaranteed to treat what they're handed as immutable, and an
            # in-place mutation by one caller must never corrupt what every later cache hit
            # for this key sees.
            with self._cache_lock:
                cached_config = self._deserialization_cache.get(cache_key)
                if cached_config is not None:
                    self._deserialization_cache.move_to_end(cache_key)
                    return deepcopy(cached_config)

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

        # Cache the parsed config for future use (only when opted in).
        # Store a deepcopy so this caller (who gets the original `config` back below)
        # can't mutate the cached entry out from under future cache hits, and evict the
        # least-recently-used entry once we're over the cap so a long dev session with
        # many edit/reload cycles doesn't grow this dict without bound.
        if cache_enabled:
            with self._cache_lock:
                self._deserialization_cache[cache_key] = deepcopy(config)
                self._deserialization_cache.move_to_end(cache_key)
                while len(self._deserialization_cache) > _CACHE_MAX_ENTRIES:
                    self._deserialization_cache.popitem(last=False)

        return config

    def compute_include_aware_hash(self, file_path: str, file_contents: bytes,
                                   visited: set = None) -> str:
        """
        Compute a content hash for a file that also incorporates the contents of
        every file it (transitively) includes.

        For HOCON, `include` directives are inlined at parse time, so a parsed
        result embeds a snapshot of its included files. Hashing only the top
        file's bytes would let a change to a shared included file (e.g.
        aaosa.hocon or llm_config.hocon) go unnoticed, serving a stale cached
        parse. Folding the included files' hashes in makes any such change
        invalidate the dependent's cache key.

        :param file_path: Path to the file whose hash is being computed
        :param file_contents: The bytes of that file
        :param visited: Set of already-visited absolute paths, guarding against
                        include cycles. Internal use for recursion.
        :return: A hex digest combining this file and its transitive includes.
        """
        hasher = hashlib.sha256()
        hasher.update(file_contents)

        # Only HOCON files support includes; JSON has none to follow.
        if not file_path.endswith(".hocon"):
            return hasher.hexdigest()

        if visited is None:
            visited = set()
        visited.add(os.path.abspath(file_path))

        base_dir: str = os.path.dirname(os.path.abspath(file_path))
        for match in _HOCON_INCLUDE_PATTERN.finditer(file_contents):
            raw_path: str = match.group(1).decode("utf-8", errors="replace")
            included_path: str = self.resolve_include_path(raw_path, base_dir)
            if included_path is None:
                continue

            abs_included: str = os.path.abspath(included_path)
            if abs_included in visited:
                # Already accounted for; avoids infinite recursion on include cycles.
                continue

            try:
                with open(included_path, "rb") as included_obj:
                    included_contents: bytes = included_obj.read()
            except OSError:
                # If we cannot read the include, skip it here. The actual parse
                # will surface the real error with proper context.
                continue

            # Mix in the included file's own (transitive) hash.
            included_hash: str = self.compute_include_aware_hash(included_path, included_contents, visited)
            hasher.update(b"\x00")
            hasher.update(included_hash.encode("ascii"))

        return hasher.hexdigest()

    @staticmethod
    def resolve_include_path(raw_path: str, base_dir: str) -> str:
        """
        Resolve a raw HOCON include path to an existing local file.

        Include paths may be relative to the including file's directory or to
        the current working directory (e.g. "registries/aaosa.hocon"). Try both
        and return the first that exists. Non-local includes (URLs) resolve to
        None and are ignored.

        :param raw_path: The path string captured from the include directive
        :param base_dir: The directory of the including file
        :return: A path to an existing file, or None if none was found.
        """
        if not raw_path or "://" in raw_path:
            return None

        candidates = []
        if os.path.isabs(raw_path):
            candidates.append(raw_path)
        else:
            # Relative to the including file's directory ...
            candidates.append(os.path.join(base_dir, raw_path))
            # ... and relative to the current working directory (project root).
            candidates.append(raw_path)

        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate

        return None

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
