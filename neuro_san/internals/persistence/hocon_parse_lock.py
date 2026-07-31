
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

    Known trade-off: pyhocon resolves "include" directives (file or URL reads)
    inside the parse, so that I/O happens while the lock is held. Ordinary
    local-file includes (include "registries/foo.hocon") are fine: their reads
    are sub-millisecond and their nested parse happens inside pyhocon, below
    this lock, so there is no reentrancy. The hazard is unbounded I/O: pyhocon
    fetches "include url(...)" with no timeout, and a file include on a hung
    network mount blocks the same way, stalling every other HOCON parse (and
    every fork, per the hooks below) instead of just its own thread. Do not
    use "include url(...)" in served registries.
    """

    # One lock for the whole process, shared by all instances,
    # because the pyparsing state it guards is process-global.
    # Never rebind this attribute: the register_at_fork hooks below capture
    # bound methods of this exact object and cannot be re-registered, so a
    # replacement lock would serialize parses without fork protection.
    lock: ClassVar[Lock] = Lock()

    if hasattr(os, "register_at_fork"):
        # Runs once, when the class body is executed at import time.
        # Without this, an os.fork() happening while some thread holds the lock
        # (e.g. AGENT_MANIFEST_CONCURRENCY_CONTEXT="fork" while a watcher thread
        # is mid-parse) would give the child a lock that can never be released,
        # deadlocking the child's first HOCON parse. This mirrors what the
        # standard library logging module does for its module lock: acquire
        # before the fork, release in the parent, and _at_fork_reinit() in the
        # child. The child must reinit rather than release: on CPython <= 3.12
        # platforms without POSIX semaphores (e.g. macOS), a waiter blocked in
        # acquire() can hold the lock's internal pthread mutex at the fork
        # instant, and a child-side release() would hang on that inherited
        # mutex whose owner is dead (see bpo-40089). Windows has no fork,
        # hence the hasattr guard.
        # The bare "lock" references are required: the HoconParseLock name is
        # not bound until the class body finishes executing.
        os.register_at_fork(
            before=lock.acquire,
            after_in_parent=lock.release,
            # pylint: disable=no-member,protected-access
            after_in_child=lock._at_fork_reinit,
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
