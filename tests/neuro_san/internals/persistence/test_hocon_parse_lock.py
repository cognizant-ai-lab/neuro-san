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
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from unittest.mock import patch

import pytest

from leaf_common.serialization.format.hocon_serialization_format import HoconSerializationFormat

from neuro_san.internals.persistence.abstract_async_config_restorer import AbstractAsyncConfigRestorer
from neuro_san.internals.persistence.hocon_parse_lock import HoconParseLock


class ConcreteRestorer(AbstractAsyncConfigRestorer):
    """Minimal concrete subclass – inherits all behaviour from the abstract base."""


VALID_DICT: Dict[str, Any] = {"key": "value", "nested": {"a": 1}}

# Directory containing .json and .hocon fixture files used by the tests.
FIXTURES_DIR: Path = Path(__file__).parent.parent.parent.parent / "fixtures"


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
        done = threading.Event()

        with HoconParseLock():
            thread = threading.Thread(
                target=lambda: (self.deserialize("valid.hocon"), done.set()), daemon=True)
            thread.start()
            # The parse must not complete while the lock is held.
            assert not done.wait(timeout=0.3)

        # Once released, the parse completes promptly.
        assert done.wait(timeout=5.0)
        thread.join(timeout=5.0)

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

    @pytest.mark.skipif(not hasattr(os, "fork"), reason="os.fork not available on this platform")
    def test_fork_while_lock_held_leaves_child_usable(self) -> None:
        """
        A fork racing an in-flight parse must not deadlock the child
        (AGENT_MANIFEST_CONCURRENCY_CONTEXT="fork" forks workers while other
        threads may be parsing). The register_at_fork hooks hold the lock
        across the fork so the child starts with it released.
        """
        hold_seconds: float = 0.5

        def hold_lock():
            with HoconParseLock():
                time.sleep(hold_seconds)

        holder = threading.Thread(target=hold_lock, daemon=True)
        holder.start()
        # Make sure the holder actually has the lock before forking.
        while not HoconParseLock.lock.locked():
            time.sleep(0.001)

        start: float = time.monotonic()
        pid: int = os.fork()
        if pid == 0:
            # Child: never return control to pytest; report via exit code.
            try:
                if not HoconParseLock.lock.acquire(timeout=5.0):  # pylint: disable=consider-using-with
                    os._exit(1)
                HoconParseLock.lock.release()
                config: Dict[str, Any] = self.deserialize("valid.hocon")
                os._exit(0 if config == VALID_DICT else 2)
            except BaseException:   # pylint: disable=broad-except
                os._exit(3)

        # Parent: the before-fork hook must have waited out the holder.
        assert time.monotonic() - start >= hold_seconds * 0.5

        _, status = os.waitpid(pid, 0)
        assert os.WEXITSTATUS(status) == 0

        holder.join(timeout=5.0)
        assert not HoconParseLock.lock.locked()
