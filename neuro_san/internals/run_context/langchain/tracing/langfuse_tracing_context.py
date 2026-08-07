
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
from __future__ import annotations

from typing import Any
from typing import Dict
from typing import Optional
from typing import Type

import os
import threading

from contextvars import ContextVar
from datetime import datetime
from logging import getLogger
from socket import gethostname

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.runnables.base import Runnable
from langchain_core.tracers.context import register_configure_hook

from leaf_common.config.resolver_util import ResolverUtil

from neuro_san.internals.interfaces.run_target import RunTarget
from neuro_san.internals.interfaces.tracing_context import TracingContext
from neuro_san.internals.run_context.langchain.tracing.langchain_tracing_context import LangChainTracingContext

# Conventional name for the ContextVar carrying a langfuse CallbackHandler in
# langchain's configure hooks.  Other components (e.g. the neuro-san-studio
# LangfusePlugin) use the same name; it is the contract by which competing
# registrations detect each other and avoid reporting every span twice.
LANGFUSE_HANDLER_VAR_NAME: str = "langfuse_handler"


class LangfuseTracingContext(LangChainTracingContext):
    """
    TracingContext implementation for runs that use Langfuse.
    """

    # Global context variable for the langfuse callback handler.
    # Populated lazily by _ensure_registered() on first construction so that
    # merely importing this module (or having langfuse installed with keys in
    # the environment) has no side effects.  See https://github.com/cognizant-ai-lab/neuro-san/issues/1191
    HANDLER_CONTEXT_VAR: Optional[ContextVar] = None

    # Guards the one-time registration per process.
    _REGISTER_LOCK = threading.Lock()

    @classmethod
    def _ensure_registered(cls) -> ContextVar:
        """
        Globally register the Langfuse CallbackHandler, if available.
        This is really the only way we can do this with langchain managing span parentage.

        Called from the constructor rather than at class-load time so that
        registration (and the Langfuse client the handler constructs from the
        LANGFUSE_* env vars) only happens when a LangfuseTracingContext is
        actually created - that is, when LANGFUSE_ENABLED is true per the
        LangChainTracingContextFactory.  Merely installing langfuse with keys
        in the environment must not start exporting traces.

        Caveat: registration is a process-lifetime one-way door.  Once the
        first enabled request has registered the handler with langchain,
        flipping LANGFUSE_ENABLED to false in the same process only stops the
        per-request wrapping (root AGENT span, session/user metadata) - the
        already-registered handler keeps exporting bare traces until the
        process is restarted.  For LANGFUSE_ENABLED to fully disable tracing
        it must be false before the process constructs its first
        LangfuseTracingContext - operationally, false from process start.

        :return: The ContextVar carrying the langfuse callback handler.
        :raises ValueError: (from ResolverUtil) when langfuse tracing is
                wanted but the langfuse package is not installed, with the
                standard "pip install" guidance in the message.  Nothing is
                cached in that case, so the next construction retries the
                resolution - a transient import failure must not poison
                tracing for the rest of the process.
        """
        with cls._REGISTER_LOCK:
            if cls.HANDLER_CONTEXT_VAR is not None:
                # Already done
                return cls.HANDLER_CONTEXT_VAR

            # If some other component in this process already registered a
            # langfuse handler hook, reuse its handler instead of registering
            # a second one.  langchain dedupes hook handlers by object
            # identity only, so a second handler instance would make every
            # span get reported twice.
            existing: Optional[ContextVar] = cls._find_existing_handler_hook()
            if existing is not None:
                return cls._adopt_existing_handler_hook(existing)

            # See if we can create a new langfuse handler instance.
            # Use lazy loading to prevent installing the world.  When the
            # optional package is missing this raises the standard actionable
            # error, before anything below mutates the environment or caches
            # registration state.
            callback_handler_type: Type[BaseCallbackHandler] = \
                ResolverUtil.create_type("langfuse.langchain.CallbackHandler",
                                         install_if_missing="langfuse")

            # We only get here when langfuse tracing is wanted, so keep the
            # langfuse SDK's own kill switch in agreement, while respecting
            # a value that was explicitly set in the environment.  This
            # must happen before the handler is instantiated - the SDK
            # reads the var once, at client construction.
            # Caveats: an explicitly set LANGFUSE_TRACING_ENABLED=false
            # only mutes export - the SDK makes every span non-recording,
            # but the handler below is still registered and dispatched on
            # every langchain event, and create_main_span() still runs.
            # Changing the var in a running process has no effect.  To
            # turn tracing fully off, set LANGFUSE_ENABLED=false and
            # restart the process.
            os.environ.setdefault("LANGFUSE_TRACING_ENABLED", "true")

            # Create the callback handler instance
            callback_handler: BaseCallbackHandler = callback_handler_type()
            # Langfuse's handler is synchronous, so LangChain routes every trace event through
            # a thread pool. Each of those ThreadPoolExecutor.submit calls grabs a process-global lock,
            # and with thousands of events × 50 requests, threads just queued on it — 76% of active time
            # in the profile. This run_inline = True tells LangChain to call the handler directly,
            # skipping the thread pool entirely.
            callback_handler.run_inline = True

            # Carry the handler as the ContextVar default rather than via set():
            # a set() is only visible in contexts descended from the setting
            # thread, while a default is visible in every thread.
            context_var = ContextVar(LANGFUSE_HANDLER_VAR_NAME, default=callback_handler)
            register_configure_hook(context_var, inheritable=True)
            cls.HANDLER_CONTEXT_VAR = context_var
            return context_var

    @classmethod
    def _adopt_existing_handler_hook(cls, existing: ContextVar) -> ContextVar:
        """
        Reuse a langfuse handler hook that some other component in this
        process (e.g. a deployment wrapper) already registered with langchain.

        :param existing: The ContextVar of the already-registered hook.
        :return: The ContextVar to cache as HANDLER_CONTEXT_VAR.
        """
        foreign_handler: Optional[BaseCallbackHandler] = existing.get()
        if foreign_handler is not None:
            # Re-carry the same handler instance in our own ContextVar as its
            # default so it is visible in every thread, not only in contexts
            # descended from wherever the foreign component set() it.
            # Registering a second hook with the same instance is safe:
            # langchain adds a hook's handler only if that exact object is
            # not already among the run's handlers.
            context_var = ContextVar(LANGFUSE_HANDLER_VAR_NAME, default=foreign_handler)
            register_configure_hook(context_var, inheritable=True)
            cls.HANDLER_CONTEXT_VAR = context_var
            return context_var

        # The foreign handler is not visible from this context: it was either
        # populated via set() in another thread, or langchain creates it
        # lazily from the hook's handler_class.  Use the foreign hook as-is;
        # get() returning None here does not mean langfuse is missing.
        getLogger(cls.__name__).warning(
            "Adopted an existing langfuse handler hook whose handler is not "
            "visible from this context; tracing may be unavailable on some threads.")
        cls.HANDLER_CONTEXT_VAR = existing
        return existing

    @staticmethod
    def _find_existing_handler_hook() -> Optional[ContextVar]:
        """
        :return: The ContextVar of a configure hook that some other component
                already registered for a langfuse handler, identified by the
                conventional ContextVar name "langfuse_handler".
                None if there is no such hook.
        """
        try:
            # Read-only peek at a private langchain structure, with a graceful
            # fallback if it ever disappears.  There is no public API for
            # enumerating configure hooks.
            # pylint: disable=import-outside-toplevel
            from langchain_core.tracers.context import _configure_hooks
        except ImportError:
            return None

        for hook in _configure_hooks:
            hook_var: ContextVar = hook[0]
            if getattr(hook_var, "name", None) == LANGFUSE_HANDLER_VAR_NAME:
                return hook_var

        return None

    def __init__(self, run_target: RunTarget,
                 config: Dict[str, Any],
                 parent_context: LangfuseTracingContext = None):
        """
        Constructor

        :param run_target: The RunTarget instance to be traced
        :param config: The configuration for the tracing context
        :param parent_context: The parent instance to riff from.
        """
        super().__init__(run_target=run_target, config=config)

        # Keep a reference to the parent context
        self.parent_context: LangfuseTracingContext = parent_context

        # Keep a session_id for any child TracingContext to use in its langfuse config for the run.
        self.session_id: str = None

        # Register the langfuse handler with langchain (idempotent; first
        # construction in the process does the work).  Raises the standard
        # actionable error if langfuse tracing is wanted but the package is
        # not installed.
        self._ensure_registered()

        # Keep track of some Langfuse state

        # No need to ResolverUtil absolutely everything, but we still need to locally import
        # for the rest of the system to behave without langfuse installed.
        # pylint: disable=import-outside-toplevel
        try:
            from langfuse import Langfuse
            from langfuse import get_client
            from opentelemetry.util._decorator import _AgnosticContextManager
        except ImportError:
            # Reachable when a foreign "langfuse_handler" hook was adopted
            # (which skips handler resolution above) but langfuse itself is
            # not importable.  Re-run the standard resolution so the failure
            # carries the consistent actionable message; if langfuse resolves
            # (i.e. something else failed to import), re-raise as-is.
            ResolverUtil.create_type("langfuse.langchain.CallbackHandler",
                                     install_if_missing="langfuse")
            raise

        self.langfuse_client: Langfuse = get_client()
        self.main_span: _AgnosticContextManager[Any] = None

    def clone(self) -> TracingContext:
        """
        Creates a copy the tracing context.

        :return: A clone of the tracing context.
        """
        clone = LangfuseTracingContext(run_target=self.run_target, config=self.config, parent_context=self)
        return clone

    async def ainvoke(self, chain: Runnable, inputs: Any, runnable_config: Dict[str, Any]):
        """
        Invoke the chain with the inputs and config
        :param chain: The chain to invoke
        :param inputs: The inputs to the chain
        :param runnable_config: The config for the runnable
        """
        if self.main_span is not None:
            # We have a main span. Use it as the context.
            # pylint: disable=not-context-manager
            with self.main_span:
                await super().ainvoke(chain, inputs, runnable_config)
        else:
            await super().ainvoke(chain, inputs, runnable_config)

    def create_main_span(self, runnable_config: Dict[str, Any]):
        """
        Create the main span for the run
        :param runnable_config: The config for the runnable
        """

        if self.main_span is not None:
            # Already done
            return

        if self.langfuse_client is None:
            # Langfuse is not enabled
            return

        if self.parent_context is not None and self.parent_context.main_span is not None:
            # We have a parent context with a main_span. Dont do anything.
            return

        run_name: str = runnable_config.get("run_name")

        # This "agent" type gets us the nice little icon in the langfuse UI
        # According to langfuse docs, this should be safe for use in async code.
        self.main_span = self.langfuse_client.start_as_current_observation(as_type="agent", name=run_name)

    def augment_config(self, runnable_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Augment the configuration however the implementation sees fit (if at all).
        :param runnable_config: The config for the runnable
        :return: The augmented config
        """
        self.create_main_span(runnable_config)

        runnable_config["neuro_san_tracing_context"] = self

        # Get the user_id for the trace
        empty: Dict[str, Any] = {}
        request_metadata: Dict[str, Any] = runnable_config.get("metadata", empty)
        user_id: str = request_metadata.get("user_id", "<Unknown>")
        run_name = runnable_config.get("run_name")

        # Find the right session_id to use for the session components
        self.session_id: str = self.get_parent_session_id()
        if self.session_id is None:

            # Get pieces of the session_id to construct
            request_id: str = request_metadata.get("request_id", "<Unknown>")

            # It's possible we should move the addition of hostname up to the services infra.
            hostname: str = gethostname()

            # We use the time to distiguish sessions on a restarted server on the same host.
            now_str: str = datetime.now().strftime('%Y-%m-%d-%H:%M:%S.%f')

            # Create a session_id for the trace.
            self.session_id: str = f"{run_name}@{request_id}@{hostname}@{now_str}"

        elif run_name is not None:
            # Add .agent to the end to get langfuse to display the agent icon
            new_name: str = f"{run_name} (agent)"
            runnable_config["run_name"] = new_name

        request_metadata["langfuse_user_id"] = user_id
        request_metadata["langfuse_session_id"] = self.session_id
        runnable_config["metadata"] = request_metadata

        return runnable_config

    def get_parent_session_id(self):
        """
        Get the parent session id.
        We want the to be consistent for any depth of trace in the request.

        :return: The parent session id
        """
        if self.parent_context is not None:
            return self.parent_context.get_parent_session_id()

        return self.session_id

    async def flush(self):
        """
        Flush the tracing context.
        """
        # Do nothing.
        # At the end of every request, a call to Langfuse's SDK flush(), is a blocking HTTP upload.
        # It drains the whole process's span queue, not just that request's.
        # It runs on a shared event loop, so while it runs, other requests freeze.
        # The more concurrent requests, the bigger the queue, the longer everyone waited.
        # What you lose: the guarantee that a request's traces are uploaded before the request is marked done.
        # The Langfuse SDK's background thread uploads them anyway; the only real exposure is the final batch if
        # the process is killed — which is what a shutdown drain would cover.
        # if self.langfuse_client is not None:
        #    self.langfuse_client.flush()
