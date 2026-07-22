
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
"""
See class comment for details.
"""
import asyncio
import atexit
import json
import logging
import os
import sys
import threading
import time
from collections import deque
from typing import Any
from typing import Deque
from typing import List
from typing import Optional
from typing import Tuple


class LoopTimelineTracer:
    """
    sys.setprofile-based tracer that records a linear timeline of activity
    on a single asyncio event-loop thread.

    Every scheduled unit of work an asyncio loop runs -- task steps, done
    callbacks, call_soon callbacks, timer callbacks -- flows through
    asyncio.events.Handle._run(). By hooking that function's call/return
    events via sys.setprofile, this tracer captures:

      - When each scheduled unit of work started.
      - When it returned (i.e. yielded back to the loop, or finished).
      - What it was: a Task step (with the task's name) or a plain
        callback (with the callback's qualname).

    Reading a snapshot back gives you a sequence like:

        call   task_step  streaming_chat.post   t=0.000ms
        return                                  t=0.140ms
        call   callback   _add_ready_callback   t=0.145ms
        return                                  t=0.148ms
        call   task_step  agent_chat_loop       t=0.200ms
        return                                  t=1.310ms   <- this task hogged 1.1ms
        ...

    which directly answers "what is occupying my loop?"

    Design notes:
      * Ring buffer (collections.deque with maxlen) bounds memory. Old events
        drop off the front as new ones arrive.
      * The profile callback is deliberately minimal to keep tracing overhead
        low; expensive introspection (peeking at frame locals) happens only
        on 'call' events for the specific Handle._run frame.
      * f_code identity comparison (frame.f_code is _handle_run_code) is
        O(1) and avoids string matching in the hot path.
      * sys.setprofile is per-thread. This tracer must be started on the
        thread whose loop you want to trace (typically the Tornado main
        loop thread, right before IOLoop.current().start()).

    Cost: ~5-10% loop overhead depending on callback density. Fine for
    diagnostic runs and manageable for production if you keep the buffer
    small.
    """

    DEFAULT_MAX_EVENTS: int = 100_000

    # sys.setprofile 'event' string values we care about. Kept as constants so
    # the profile callback can do fast equality checks against a small, fixed
    # vocabulary.
    _EVENT_CALL: str = "call"
    _EVENT_RETURN: str = "return"

    # Semantic label values we emit for enriched call events. Keep the
    # vocabulary small so post-processing tools can filter by string.
    _LABEL_TASK_STEP: str = "task_step"
    _LABEL_CALLBACK: str = "callback"
    _LABEL_UNKNOWN: str = "unknown"

    def __init__(self, max_events: int = DEFAULT_MAX_EVENTS):
        """
        :param max_events: Maximum number of events retained in the ring
                buffer. Older events are dropped as newer ones arrive.
        """
        if max_events <= 0:
            raise ValueError("max_events must be a positive integer")
        self._events: Deque[Tuple[int, str, str, str]] = deque(maxlen=max_events)
        self._max_events: int = max_events
        self._loop_thread_ident: Optional[int] = None
        # Cache the code object of asyncio.events.Handle._run so the profile
        # callback can filter by frame.f_code identity (O(1)) instead of
        # matching by function name (string compare on every profile event).
        self._handle_run_code: Any = asyncio.events.Handle._run.__code__
        self._logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self._registered_atexit: bool = False
        self._previous_profile: Optional[Any] = None

    def start(self) -> None:
        """
        Install the sys.setprofile hook on the CURRENT thread. Must be
        called from the thread whose event loop you want to trace
        (e.g. the Tornado worker's main loop thread, right before
        IOLoop.current().start()).

        Idempotent: repeated calls from the same thread are a no-op.
        """
        if self._loop_thread_ident is not None:
            return
        self._loop_thread_ident = threading.get_ident()
        self._previous_profile = sys.getprofile()
        if self._previous_profile is not None:
            self._logger.warning(
                "LoopTimelineTracer is replacing an existing sys.setprofile hook (%r); it will be restored on stop()",
                self._previous_profile,
            )
        sys.setprofile(self._profile)
        self._logger.info(
            "LoopTimelineTracer active on thread %d (buffer=%d events)",
            self._loop_thread_ident, self._max_events)

    def stop(self) -> None:
        """
        Uninstall the sys.setprofile hook. Must be called from the same
        thread that called start(); a call from a different thread is a
        no-op (sys.setprofile is per-thread and cannot be reset from
        outside the thread).
        """
        if self._loop_thread_ident is None:
            return
        if threading.get_ident() != self._loop_thread_ident:
            return
        prev_profile = getattr(self, "_previous_profile", None)
        sys.setprofile(prev_profile)
        self._previous_profile = None
        self._loop_thread_ident = None

    def snapshot(self) -> List[Tuple[int, str, str, str]]:
        """
        Return a list copy of the current ring-buffer contents. Safe to
        call from any thread.

        :return: A list of (t_ns, phase, label, detail) tuples, oldest
                 first. Empty if tracing has not started or no events have
                 been captured.
        """
        return list(self._events)

    def dump_to_file(self, path: str) -> int:
        """
        Serialize the buffered timeline as JSONL to the given path. Each
        line is a JSON object with keys: t_ns, phase, label, detail.

        :param path: Filesystem path to write.
        :return: Number of events written.
        """
        events_snapshot: List[Tuple[int, str, str, str]] = self.snapshot()
        # Write to a tmp file and rename so partial files never appear on
        # disk even if the writer is interrupted mid-dump.
        tmp_path: str = f"{path}.{os.getpid()}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            for event in events_snapshot:
                fh.write(json.dumps({
                    "t_ns": event[0],
                    "phase": event[1],
                    "label": event[2],
                    "detail": event[3],
                }) + "\n")
        os.replace(tmp_path, path)
        return len(events_snapshot)

    def _profile(self, frame, event, _arg) -> None:
        """
        The actual sys.setprofile callback. Keep this method small and
        cheap: it runs on every C->Python and Python->C transition on
        this thread. Expensive work here dominates the measured timing
        and defeats the point of tracing.
        """
        # Fast filter: only interested in the Handle._run frame.
        if frame.f_code is not self._handle_run_code:
            return
        # Only interested in call/return events (skip c_call/c_return, exception).
        # pylint: disable=consider-using-in
        if event != self._EVENT_CALL and event != self._EVENT_RETURN:
            return
        ts_ns: int = time.monotonic_ns()
        if event == self._EVENT_CALL:
            label, detail = self._describe_handle(frame)
            self._events.append((ts_ns, self._EVENT_CALL, label, detail))
        else:
            # Return events don't need enrichment -- they close the most
            # recent open 'call'. Post-processing pairs them up.
            self._events.append((ts_ns, self._EVENT_RETURN, "", ""))

    @classmethod
    def _describe_handle(cls, frame) -> Tuple[str, str]:
        """
        Introspect the Handle._run frame's locals to identify what is
        about to run. Returns a (label, detail) pair for logging.

        This is the only introspective step in the hot path; it runs only
        on 'call' events (once per scheduled unit of work).
        """
        try:
            handle = frame.f_locals.get("self")
            callback = getattr(handle, "_callback", None)
            if callback is None:
                return cls._LABEL_UNKNOWN, ""
            # A Task step is scheduled by asyncio as a bound method of the
            # Task instance -- callback.__self__ is the Task.
            self_obj = getattr(callback, "__self__", None)
            if isinstance(self_obj, asyncio.Task):
                return cls._LABEL_TASK_STEP, self_obj.get_name()
            # Otherwise it's a plain callback (call_soon target, done cb, etc.).
            qualname: str = getattr(callback, "__qualname__", repr(callback))
            return cls._LABEL_CALLBACK, qualname
        except Exception:  # pylint: disable=broad-exception-caught
            # Anything unexpected: don't crash the profile callback.
            return cls._LABEL_UNKNOWN, ""

    def _on_exit(self, path: str) -> None:
        """
        Internal atexit callback to dump the timeline to a file. Catches
        and logs any exceptions so the process can exit cleanly.
        :param path: Destination path for the JSONL dump.
        """
        try:
            count: int = self.dump_to_file(path)
            self._logger.info(
                "LoopTimelineTracer wrote %d events to %s at shutdown",
                count, path)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logger.warning(
                "LoopTimelineTracer atexit dump failed: %s", exc)

    def register_atexit_dump(self, path: str) -> None:
        """
        Convenience: wire dump_to_file(path) into atexit so the process
        writes its final timeline on graceful shutdown. Idempotent per
        instance -- calling twice registers only once.

        :param path: Destination path for the JSONL dump.
        """
        if self._registered_atexit:
            return

        atexit.register(self._on_exit, path)
        self._registered_atexit = True
