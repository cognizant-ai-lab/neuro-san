
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

# These tests exercise the internal registration machinery directly.
# pylint: disable=protected-access

import importlib.util
import os
import sys
import threading
import types

from contextvars import ContextVar
from unittest.mock import MagicMock

import pytest

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.runnables.passthrough import RunnablePassthrough
from langchain_core.tracers.context import _configure_hooks
from langchain_core.tracers.context import register_configure_hook

import neuro_san.internals.run_context.langchain.tracing.langfuse_tracing_context as ltc_module
from neuro_san.internals.run_context.langchain.tracing.langchain_tracing_context import LangChainTracingContext
from neuro_san.internals.run_context.langchain.tracing.langchain_tracing_context_factory \
    import LangChainTracingContextFactory


def _count_langfuse_hooks() -> int:
    """
    :return: How many langchain configure hooks carry a ContextVar named "langfuse_handler".
    """
    return sum(1 for hook in _configure_hooks
               if getattr(hook[0], "name", None) == ltc_module.LANGFUSE_HANDLER_VAR_NAME)


def _install_fake_langfuse(monkeypatch) -> type:
    """
    Put a minimal fake langfuse package into sys.modules so that
    ResolverUtil.create_type("langfuse.langchain.CallbackHandler") and the
    constructor's "from langfuse import ..." both resolve without the real
    package. monkeypatch removes the entries again after the test.

    :return: The fake CallbackHandler class, which counts its instantiations.
    """
    class FakeCallbackHandler(BaseCallbackHandler):
        """Stand-in for langfuse.langchain.CallbackHandler."""
        instances_created: int = 0

        def __init__(self):
            FakeCallbackHandler.instances_created += 1

    fake_langchain_module = types.ModuleType("langfuse.langchain")
    fake_langchain_module.CallbackHandler = FakeCallbackHandler

    fake_root_module = types.ModuleType("langfuse")
    fake_root_module.langchain = fake_langchain_module
    fake_root_module.Langfuse = MagicMock(name="Langfuse")
    fake_root_module.get_client = MagicMock(name="get_client", return_value=MagicMock(name="langfuse_client"))

    monkeypatch.setitem(sys.modules, "langfuse", fake_root_module)
    monkeypatch.setitem(sys.modules, "langfuse.langchain", fake_langchain_module)
    return FakeCallbackHandler


@pytest.fixture(scope="module", autouse=True)
def dummy_llm_key():
    """
    These tests never call an LLM, but the repo-wide conftest fixture skips
    unmarked tests when OPENAI_API_KEY is unset. Scope a dummy value to this
    module so the registration tests always run.
    """
    had_key = "OPENAI_API_KEY" in os.environ
    if not had_key:
        os.environ["OPENAI_API_KEY"] = "dummy-never-used-by-these-tests"
    yield
    if not had_key:
        os.environ.pop("OPENAI_API_KEY", None)


class TestLangfuseTracingContextRegistration:
    """
    Test cases for the lazy, once-per-process registration of the Langfuse
    CallbackHandler (https://github.com/cognizant-ai-lab/neuro-san/issues/1191).
    """

    @pytest.fixture(autouse=True)
    def clean_registration_state(self):
        """
        Registration mutates process-global state (the class attributes,
        langchain's configure-hook list, and the derived env var), so snapshot
        and restore all of it around every test. Any langfuse hook registered
        earlier in the pytest session (e.g. by a test that constructed a real
        tracing context) is removed for the duration so each test starts from
        an unregistered process state.
        """
        hooks_before = list(_configure_hooks)
        _configure_hooks[:] = [hook for hook in hooks_before
                               if getattr(hook[0], "name", None) != ltc_module.LANGFUSE_HANDLER_VAR_NAME]
        var_before = ltc_module.LangfuseTracingContext.HANDLER_CONTEXT_VAR
        adopted_before = ltc_module.LangfuseTracingContext._ADOPTED_FOREIGN_HOOK
        ltc_module.LangfuseTracingContext.HANDLER_CONTEXT_VAR = None
        ltc_module.LangfuseTracingContext._ADOPTED_FOREIGN_HOOK = False
        tracing_enabled_before = os.environ.get("LANGFUSE_TRACING_ENABLED")
        yield
        ltc_module.LangfuseTracingContext.HANDLER_CONTEXT_VAR = var_before
        ltc_module.LangfuseTracingContext._ADOPTED_FOREIGN_HOOK = adopted_before
        _configure_hooks[:] = hooks_before
        if tracing_enabled_before is None:
            os.environ.pop("LANGFUSE_TRACING_ENABLED", None)
        else:
            os.environ["LANGFUSE_TRACING_ENABLED"] = tracing_enabled_before

    def test_import_has_no_side_effects(self, monkeypatch):
        """
        Re-executing the module (as an import would) must not register a
        configure hook or build a handler, even with langfuse importable and
        keys present. This is the core of issue #1191: before the fix,
        class-load did both.
        """
        _install_fake_langfuse(monkeypatch)
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

        hooks_before = _count_langfuse_hooks()

        # Execute the module source into an isolated module object rather than
        # importlib.reload()-ing it in place: a reload would swap the class out
        # from under other modules that hold a reference to it, making the
        # test suite order-dependent.
        spec = importlib.util.spec_from_file_location("ltc_isolated_reimport", ltc_module.__file__)
        isolated = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(isolated)

        assert isolated.LangfuseTracingContext.HANDLER_CONTEXT_VAR is None
        assert _count_langfuse_hooks() == hooks_before

    def test_registers_once_and_only_once(self, monkeypatch):
        """
        _ensure_registered() must register exactly one hook per process no
        matter how many times it is called, and hand back the same ContextVar.
        """
        fake_handler_class = _install_fake_langfuse(monkeypatch)

        first = ltc_module.LangfuseTracingContext._ensure_registered()
        second = ltc_module.LangfuseTracingContext._ensure_registered()

        assert first is second
        assert isinstance(first.get(), fake_handler_class)
        assert fake_handler_class.instances_created == 1
        assert _count_langfuse_hooks() == 1

    def test_handler_visible_from_other_threads(self, monkeypatch):
        """
        The handler must be carried as the ContextVar default, not via set():
        a set() is invisible to sibling threads, which would make traces
        silently vanish for requests handled off the registering thread.
        """
        _install_fake_langfuse(monkeypatch)
        handler_var = ltc_module.LangfuseTracingContext._ensure_registered()

        seen_in_thread = []
        thread = threading.Thread(target=lambda: seen_in_thread.append(handler_var.get()))
        thread.start()
        thread.join()

        assert seen_in_thread[0] is handler_var.get()
        assert seen_in_thread[0] is not None

    def test_adopts_visible_foreign_handler_in_own_var(self, monkeypatch):
        """
        If some other component (e.g. a deployment wrapper) already registered
        a langfuse handler hook and its handler is visible, reuse that same
        instance rather than creating a second handler (a second instance
        would report every span twice, neuro-san-studio#1292) — but carry it
        in our own ContextVar as the default, so it stays visible on threads
        the foreign component's set() never reached.
        """
        fake_handler_class = _install_fake_langfuse(monkeypatch)

        foreign_handler = BaseCallbackHandler()
        foreign_var = ContextVar(ltc_module.LANGFUSE_HANDLER_VAR_NAME, default=foreign_handler)
        register_configure_hook(foreign_var, inheritable=True)

        adopted = ltc_module.LangfuseTracingContext._ensure_registered()

        assert adopted.get() is foreign_handler
        assert fake_handler_class.instances_created == 0

        seen_in_thread = []
        thread = threading.Thread(target=lambda: seen_in_thread.append(adopted.get()))
        thread.start()
        thread.join()
        assert seen_in_thread[0] is foreign_handler

    def test_adoption_does_not_double_dispatch(self, monkeypatch):
        """
        After reusing a visible foreign handler, two hooks may carry the same
        instance; langchain's identity dedupe must still dispatch each run
        event to that handler exactly once.
        """
        _install_fake_langfuse(monkeypatch)

        events = []

        class RecordingHandler(BaseCallbackHandler):
            """Counts on_chain_start calls per run."""
            def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
                events.append(run_id)

        foreign_var = ContextVar(ltc_module.LANGFUSE_HANDLER_VAR_NAME, default=RecordingHandler())
        register_configure_hook(foreign_var, inheritable=True)

        ltc_module.LangfuseTracingContext._ensure_registered()
        RunnablePassthrough().invoke("x")

        assert len(events) > 0
        assert len(events) == len(set(events))

    def test_adopts_invisible_foreign_hook_without_raising(self, monkeypatch):
        """
        A foreign hook whose handler is NOT visible from this context (e.g.
        populated via set() on another thread, or created lazily by langchain
        from the hook's handler_class) is adopted as-is, and constructing the
        tracing context must not raise the misleading "pip install langfuse"
        error — langfuse is installed; we just cannot see the handler.
        """
        fake_handler_class = _install_fake_langfuse(monkeypatch)

        foreign_var = ContextVar(ltc_module.LANGFUSE_HANDLER_VAR_NAME, default=None)
        register_configure_hook(foreign_var, inheritable=True)

        ltc_module.LangfuseTracingContext(run_target=None, config={})

        assert ltc_module.LangfuseTracingContext.HANDLER_CONTEXT_VAR is foreign_var
        assert fake_handler_class.instances_created == 0
        assert _count_langfuse_hooks() == 1

    def test_sdk_kill_switch_derived_from_langfuse_enabled(self, monkeypatch):
        """
        Registration only happens on the LANGFUSE_ENABLED=true path, so the
        SDK's own opt-out switch is defaulted to agree with it.
        """
        _install_fake_langfuse(monkeypatch)
        monkeypatch.delenv("LANGFUSE_TRACING_ENABLED", raising=False)

        ltc_module.LangfuseTracingContext._ensure_registered()

        assert os.environ.get("LANGFUSE_TRACING_ENABLED") == "true"

    def test_sdk_kill_switch_explicit_value_respected(self, monkeypatch):
        """
        An explicitly set LANGFUSE_TRACING_ENABLED must win over the derived value.
        """
        _install_fake_langfuse(monkeypatch)
        monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")

        ltc_module.LangfuseTracingContext._ensure_registered()

        assert os.environ.get("LANGFUSE_TRACING_ENABLED") == "false"

    def test_missing_langfuse_raises_actionable_error(self, monkeypatch):
        """
        LANGFUSE_ENABLED=true without the langfuse package installed must
        still raise the actionable ValueError, and must not leave a hook or a
        stray LANGFUSE_TRACING_ENABLED env mutation behind.
        A None entry in sys.modules makes the import fail deterministically,
        whether or not the real package is installed in the test environment.
        """
        monkeypatch.setitem(sys.modules, "langfuse", None)
        monkeypatch.setitem(sys.modules, "langfuse.langchain", None)
        monkeypatch.delenv("LANGFUSE_TRACING_ENABLED", raising=False)

        with pytest.raises(ValueError, match="LANGFUSE_ENABLED"):
            ltc_module.LangfuseTracingContext(run_target=None, config={})

        assert _count_langfuse_hooks() == 0
        assert "LANGFUSE_TRACING_ENABLED" not in os.environ

    def test_resolution_failure_is_not_memoized(self, monkeypatch):
        """
        A failed langfuse resolution must not poison the process: once the
        package becomes importable, the next construction registers normally
        instead of replaying the cached failure until restart.
        """
        monkeypatch.setitem(sys.modules, "langfuse", None)
        monkeypatch.setitem(sys.modules, "langfuse.langchain", None)
        with pytest.raises(ValueError, match="LANGFUSE_ENABLED"):
            ltc_module.LangfuseTracingContext(run_target=None, config={})
        assert ltc_module.LangfuseTracingContext.HANDLER_CONTEXT_VAR is None

        fake_handler_class = _install_fake_langfuse(monkeypatch)
        ltc_module.LangfuseTracingContext(run_target=None, config={})

        assert fake_handler_class.instances_created == 1
        assert _count_langfuse_hooks() == 1

    def test_construction_and_clone_share_one_registration(self, monkeypatch):
        """
        End-to-end over __init__: constructing contexts (including via clone,
        as happens per sub-agent within a request) registers exactly one hook.
        """
        fake_handler_class = _install_fake_langfuse(monkeypatch)

        context = ltc_module.LangfuseTracingContext(run_target=None, config={})
        context.clone()
        ltc_module.LangfuseTracingContext(run_target=None, config={})

        assert fake_handler_class.instances_created == 1
        assert _count_langfuse_hooks() == 1

    def test_factory_flag_off_never_registers(self, monkeypatch):
        """
        With LANGFUSE_ENABLED unset, the factory hands back the plain
        LangChainTracingContext and nothing registers: keys sitting in the
        environment are inert. (Before the fix, import alone registered.)
        """
        _install_fake_langfuse(monkeypatch)
        monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

        factory = LangChainTracingContextFactory()
        tracing_context = factory.create_tracing_context(config={}, run_target=None)

        assert type(tracing_context) is LangChainTracingContext  # pylint: disable=unidiomatic-typecheck
        assert ltc_module.LangfuseTracingContext.HANDLER_CONTEXT_VAR is None
        assert _count_langfuse_hooks() == 0
