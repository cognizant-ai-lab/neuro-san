
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
See class comment for details
"""

from typing import Any
from typing import Dict
from typing import Optional

import logging
import os
import platform
import sys
import sysconfig


class GilStateReporter:
    """
    Reports the current state of the CPython Global Interpreter Lock at server
    startup, so logs make it unambiguous whether a process is actually running
    free-threaded (no-GIL) or not.

    Three independent facts determine GIL behavior; this reports all of them:
      * free-threaded BUILD  -- is this a 3.13t/3.14t interpreter at all
                                (sysconfig "Py_GIL_DISABLED")?
      * runtime GIL state    -- is the GIL enabled right now
                                (sys._is_gil_enabled(), Python 3.13+)? On a
                                free-threaded build this can be True because a
                                loaded C/Rust extension that is not free-thread
                                safe caused CPython to re-enable it.
      * PYTHON_GIL override   -- "0" forces the GIL off, "1" forces it on,
                                unset lets the interpreter decide.

    Note the runtime state is point-in-time: on a free-threaded build with
    PYTHON_GIL unset, importing a not-yet-safe extension LATER can still flip the
    GIL back on. Report after the bulk of imports (e.g. at server startup) for
    the most representative reading; PYTHON_GIL=0 makes the reading definitive.
    """

    @staticmethod
    def get_state() -> Dict[str, Any]:
        """
        :return: A dict describing the GIL/free-threading state of this process.
                 "gil_enabled" is None when the interpreter is too old to query
                 (pre-3.13), where the GIL is always enabled.
        """
        gil_query = getattr(sys, "_is_gil_enabled", None)
        # pylint: disable=not-callable
        gil_enabled: Optional[bool] = gil_query() if callable(gil_query) else None
        return {
            "implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "free_threaded_build": bool(int(sysconfig.get_config_var("Py_GIL_DISABLED") or 0)),
            "gil_enabled": gil_enabled,
            "python_gil_env": os.environ.get("PYTHON_GIL"),
        }

    @staticmethod
    def report(logger: Optional[logging.Logger] = None) -> Dict[str, Any]:
        """
        Log a one-line summary of the current GIL state and return the state dict.
        Emits a WARNING when a free-threaded build is running WITH the GIL (i.e.
        free-threading is not actually in effect); INFO otherwise.

        :param logger: The logger to use. Defaults to this module's logger.
        :return: The same dict returned by get_state().
        """
        if logger is None:
            logger = logging.getLogger(__name__)

        state: Dict[str, Any] = GilStateReporter.get_state()
        runtime: str = f"{state['implementation']} {state['python_version']}"
        env: Optional[str] = state["python_gil_env"]
        env_str: str = "unset" if env is None else env

        if not state["free_threaded_build"]:
            logger.info(
                "GIL state: standard CPython build (GIL always enabled). %s. PYTHON_GIL=%s",
                runtime, env_str)
        elif state["gil_enabled"] is False:
            logger.info(
                "GIL state: free-threaded build, GIL DISABLED - free-threading active. %s. PYTHON_GIL=%s",
                runtime, env_str)
        elif state["gil_enabled"] is True:
            logger.warning(
                "GIL state: free-threaded build but GIL is ENABLED - free-threading NOT in effect "
                "(a loaded native extension re-enabled it, or PYTHON_GIL=1). %s. PYTHON_GIL=%s",
                runtime, env_str)
        else:
            logger.info(
                "GIL state: free-threaded build; runtime GIL state not queryable on this interpreter. "
                "%s. PYTHON_GIL=%s",
                runtime, env_str)

        return state
