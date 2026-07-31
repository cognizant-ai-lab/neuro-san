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

import os
import signal
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from unittest.mock import patch

import pytest

from leaf_common.serialization.format.hocon_serialization_format import HoconSerializationFormat

from neuro_san.internals.persistence.hocon_parse_lock import HoconParseLock
from tests.neuro_san.internals.persistence.restorer_test_helpers import ConcreteRestorer
from tests.neuro_san.internals.persistence.restorer_test_helpers import FIXTURES_DIR
from tests.neuro_san.internals.persistence.restorer_test_helpers import VALID_DICT


class TrackingHoconSerializationFormat(HoconSerializationFormat):
    """
    HoconSerializationFormat that records how many to_object() calls are in
    flight simultaneously. Class-level state so the tracking survives the
    per-call instantiation done by deserialize_file_contents().
    """

    counter_lock = threading.Lock()
    in_flight: int = 0
    max_in_flight: int = 0

    @classmethod
    def reset(cls):
        """Reset the concurrency counters."""
        cls.in_flight = 0
        cls.max_in_flight = 0

    def to_object(self, fileobj: BytesIO) -> Dict[str, Any]:
        cls = TrackingHoconSerializationFormat
        with cls.counter_lock:
            cls.in_flight += 1
            cls.max_in_flight = max(cls.max_in_flight, cls.in_flight)
        # Widen the window so that unserialized concurrent parses would overlap.
        time.sleep(0.05)
        try:
            return super().to_object(fileobj)
        finally:
            with cls.counter_lock:
                cls.in_flight -= 1


class TestHoconParseLock:
    """
    Tests that all HOCON deserialization is serialized through HoconParseLock.

    pyhocon rebuilds its pyparsing grammar per parse call while mutating
    process-global pyparsing state, so concurrent parses corrupt each other
    (issue #1183). These tests pin the mutual-exclusion behavior without
    depending on winning the underlying (rare) race.
    """

    @staticmethod
    def deserialize(filename: str) -> Dict[str, Any]:
        """Run a fixture file through deserialize_file_contents."""
        restorer = ConcreteRestorer(file_purpose="test config")
        path: Path = FIXTURES_DIR / filename
        return restorer.deserialize_file_contents(str(path), path.read_bytes())

    @staticmethod
    def reap_child(pid: int, timeout: float = 30.0) -> int:
        """
        Wait for a forked child with a deadline so a hung child cannot
        stall the whole pytest run, killing it if the deadline passes.

        :param pid: The child process id to wait for
        :param timeout: Seconds to wait before SIGKILLing the child
        :return: the raw waitpid status of the child
        """
        deadline: float = time.monotonic() + timeout
        while time.monotonic() < deadline:
            reaped, status = os.waitpid(pid, os.WNOHANG)
            if reaped == pid:
                return status
            time.sleep(0.01)

        # Child overran the deadline: kill and reap so nothing leaks.
        # waitstatus_to_exitcode() will report -SIGKILL, failing the caller's
        # assertion with a recognizable value instead of hanging the run.
        os.kill(pid, signal.SIGKILL)
        _, status = os.waitpid(pid, 0)
        return status

    def test_concurrent_hocon_parses_are_mutually_exclusive(self) -> None:
        """No two HOCON parses may ever be in flight at the same time."""
        TrackingHoconSerializationFormat.reset()
        target: str = "neuro_san.internals.persistence.abstract_async_config_restorer.HoconSerializationFormat"
        with patch(target, TrackingHoconSerializationFormat):
            with ThreadPoolExecutor(max_workers=8) as executor:
                results: List[Dict[str, Any]] = list(
                    executor.map(lambda _: self.deserialize("valid.hocon"), range(16)))

        assert TrackingHoconSerializationFormat.max_in_flight == 1
        for result in results:
            assert result == VALID_DICT

    def test_hocon_deserialize_waits_for_lock(self) -> None:
        """A HOCON parse blocks while another thread holds HoconParseLock."""
        started = threading.Event()
        done = threading.Event()

        def parse_then_flag():
            started.set()
            self.deserialize("valid.hocon")
            done.set()

        with HoconParseLock():
            thread = threading.Thread(target=parse_then_flag, daemon=True)
            thread.start()
            # Confirm the worker is actually running before the negative wait,
            # so a slow-to-schedule thread cannot false-pass the assertion below.
            assert started.wait(timeout=5.0)
            # The parse must not complete while the lock is held.
            assert not done.wait(timeout=0.3)

        # Once released, the parse completes promptly.
        assert done.wait(timeout=5.0)
        thread.join(timeout=5.0)
        assert not thread.is_alive()

    def test_json_deserialize_does_not_use_lock(self) -> None:
        """JSON parsing shares no pyparsing state and must not funnel through the lock."""
        done = threading.Event()

        with HoconParseLock():
            thread = threading.Thread(
                target=lambda: (self.deserialize("valid.json"), done.set()), daemon=True)
            thread.start()
            # The JSON parse completes even though the HOCON lock is held.
            assert done.wait(timeout=5.0)
        thread.join(timeout=5.0)
        assert not thread.is_alive()

    @pytest.mark.skipif(not hasattr(os, "fork"), reason="os.fork not available on this platform")
    def test_fork_while_lock_held_leaves_child_usable(self) -> None:
        """
        A fork racing an in-flight parse must not deadlock the child
        (AGENT_MANIFEST_CONCURRENCY_CONTEXT="fork" forks workers while other
        threads may be parsing). The register_at_fork hooks hold the lock
        across the fork so the child starts with it released.
        """
        hold_seconds: float = 0.5
        released = threading.Event()

        def hold_lock():
            with HoconParseLock():
                time.sleep(hold_seconds)
                # Set strictly before the lock release that lets the
                # before-fork hook's acquire (and hence the fork) proceed.
                released.set()

        holder = threading.Thread(target=hold_lock, daemon=True)
        holder.start()
        # Make sure the holder actually has the lock before forking.
        while not HoconParseLock.lock.locked():
            time.sleep(0.001)

        pid: int = os.fork()
        if pid == 0:
            # Child: never return control to pytest; report via exit code.
            try:
                # pylint: disable=consider-using-with
                if not HoconParseLock.lock.acquire(timeout=5.0):
                    os._exit(1)
                HoconParseLock.lock.release()
                config: Dict[str, Any] = self.deserialize("valid.hocon")
                os._exit(0 if config == VALID_DICT else 2)
            except BaseException:   # pylint: disable=broad-except
                # Surface the real error on inherited stderr before exiting,
                # so CI failures are not just an opaque exit code.
                traceback.print_exc()
                os._exit(3)

        # Parent: capture hook-ordering evidence at the instant fork returned,
        # then always reap (deadline-bounded) before asserting anything.
        released_at_fork: bool = released.is_set()
        status: int = self.reap_child(pid)

        # The before-fork hook must have waited out the holder: released is
        # set inside the holder's with-block, so it is visible by the time
        # the hook's acquire() let the fork proceed. No wall-clock arithmetic.
        assert released_at_fork
        # waitstatus_to_exitcode() distinguishes signal deaths (negative
        # values) from clean exits, unlike bare WEXITSTATUS which reads 0
        # for a child killed by SIGABRT/SIGSEGV/SIGKILL.
        assert os.waitstatus_to_exitcode(status) == 0

        holder.join(timeout=5.0)
        assert not holder.is_alive()
        assert not HoconParseLock.lock.locked()
