
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
from typing import ClassVar

import os

from threading import Lock


class HoconParseLock:
    """
    Context manager serializing all in-process pyhocon parsing.

    pyhocon's ConfigParser.parse() rebuilds its pyparsing grammar on every call
    while temporarily overriding the process-global
    pyparsing.ParserElement.DEFAULT_WHITE_CHARS (see set_default_white_spaces()
    in pyhocon's config_parser.py). pyparsing elements capture that global at
    construction time, so two HOCON parses running concurrently in the same
    process can poison each other's grammar mid-build. Symptoms are
    non-deterministic parse failures on perfectly valid files: spurious
    ParseExceptions ("Expected end of text, found '\\n'"), empty parse results
    (surfacing as "Nothing to validate." validation errors), or
    ConfigWrongTypeExceptions.
    See https://github.com/cognizant-ai-lab/neuro-san/issues/1183 and
    https://github.com/pyparsing/pyparsing/issues/89 for details.

    Every code path that parses HOCON must do so under "with HoconParseLock():".
    JSON/YAML parsing shares no such global state and should not funnel through
    this lock.

    Serializing HOCON parsing does not sacrifice the speedup of parallel
    manifest reads: pyhocon parsing is pure-Python and CPU-bound, so the GIL
    already prevents real parse parallelism between threads.
    ProcessPoolExecutor-based reads are unaffected because each worker process
    has its own copy of the lock.
    """

    # One lock for the whole process, shared by all instances,
    # because the pyparsing state it guards is process-global.
    lock: ClassVar[Lock] = Lock()

    if hasattr(os, "register_at_fork"):
        # Runs once, when the class body is executed at import time.
        # Without this, an os.fork() happening while some thread holds the lock
        # (e.g. AGENT_MANIFEST_CONCURRENCY_CONTEXT="fork" while a watcher thread
        # is mid-parse) would give the child a lock that can never be released,
        # deadlocking the child's first HOCON parse. Holding the lock across the
        # fork means children always start with it released - the same treatment
        # the standard library logging module gives its module lock.
        # Windows has no fork, hence the hasattr guard.
        # The bare "lock" reference is required: the HoconParseLock name is not
        # bound until the class body finishes executing.
        os.register_at_fork(
            before=lock.acquire,
            after_in_parent=lock.release,
            after_in_child=lock.release,
        )

    def __enter__(self) -> "HoconParseLock":
        """
        Acquire the process-wide parse lock.
        :return: this instance
        """
        self.lock.acquire()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool:
        """
        Release the process-wide parse lock.

        :param exc_type: The type of any exception raised inside the with-block
        :param exc_value: The exception instance, if any
        :param traceback: The traceback, if any
        :return: False, so any exception from the with-block propagates
        """
        self.lock.release()
        return False
