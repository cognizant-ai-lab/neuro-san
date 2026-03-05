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

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Coroutine, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pyparsing.exceptions import ParseException

from neuro_san.internals.persistence.abstract_async_config_restorer import AbstractAsyncConfigRestorer


# ---------------------------------------------------------------------------
# Concrete subclass used by all tests
# ---------------------------------------------------------------------------

class ConcreteRestorer(AbstractAsyncConfigRestorer):
    """Minimal concrete subclass – inherits all behaviour from the abstract base."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_JSON: str = json.dumps({"key": "value", "nested": {"a": 1}})
INVALID_JSON: str = "{ not valid json @@@ }"

VALID_HOCON: str = 'key = "value"\nnested { a = 1 }'
INVALID_HOCON: str = "{{{{{{{{{"

VALID_DICT: Dict[str, Any] = {"key": "value", "nested": {"a": 1}}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_restorer(
    file_purpose: str = "test config",
    env_var: str = None,
    must_exist: bool = True,
    deprecated_env_var: str = None,
) -> ConcreteRestorer:
    """Create a ConcreteRestorer with sensible defaults for use in tests."""
    return ConcreteRestorer(
        file_purpose=file_purpose,
        env_var=env_var,
        must_exist=must_exist,
        deprecated_env_var=deprecated_env_var,
    )


def run(coro: Coroutine) -> Any:
    """Run a coroutine to completion using asyncio.run."""
    return asyncio.run(coro)


def write_json_file(tmp_path: Path, content: Dict[str, Any], filename: str = "config.json") -> str:
    """Write a JSON-serialised dict to a temporary file and return its path."""
    path: Path = tmp_path / filename
    path.write_text(json.dumps(content), encoding="utf-8")
    return str(path)


def write_hocon_file(tmp_path: Path, content: str, filename: str = "config.hocon") -> str:
    """Write raw HOCON content to a temporary file and return its path."""
    path: Path = tmp_path / filename
    path.write_text(content, encoding="utf-8")
    return str(path)


# pylint: disable=too-many-public-methods
class TestAbstractAsyncConfigRestorer:
    """
    Tests for AbstractAsyncConfigRestorer covering __init__, get_file_path,
    deserialize_file_contents, filter_config, restore, and async_restore.
    """

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _make_async_open_ctx(self, content: str) -> MagicMock:
        """Return a context-manager mock that yields an async-readable file."""
        mock_file: AsyncMock = AsyncMock()
        mock_file.read = AsyncMock(return_value=content)
        ctx: MagicMock = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_file)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    def _make_async_open_ctx_missing(self) -> MagicMock:
        """Return a context-manager mock that raises FileNotFoundError on enter."""
        ctx: MagicMock = MagicMock()
        ctx.__aenter__ = AsyncMock(side_effect=FileNotFoundError)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    # -----------------------------------------------------------------------
    # __init__
    # -----------------------------------------------------------------------

    def test_stores_all_constructor_args(self) -> None:
        """All constructor arguments are stored as instance attributes."""
        r: ConcreteRestorer = ConcreteRestorer("my file", env_var="MY_VAR", must_exist=False,
                                               deprecated_env_var="OLD_VAR")
        assert r.file_purpose == "my file"
        assert r.env_var == "MY_VAR"
        assert r.must_exist is False
        assert r.deprecated_env_var == "OLD_VAR"

    def test_defaults(self) -> None:
        """Optional constructor arguments default to their documented values."""
        r: ConcreteRestorer = ConcreteRestorer("cfg")
        assert r.env_var is None
        assert r.must_exist is True
        assert r.deprecated_env_var is None
        assert r.logger is not None

    # -----------------------------------------------------------------------
    # get_file_path
    # -----------------------------------------------------------------------

    def test_get_file_path_returns_explicit_file_reference(self, tmp_path: Path) -> None:
        """An explicit file_reference is returned unchanged."""
        path: str = str(tmp_path / "config.json")
        r: ConcreteRestorer = make_restorer()
        assert r.get_file_path(path) == path

    def test_get_file_path_falls_back_to_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When no file_reference is given, the value of env_var is used."""
        path: str = str(tmp_path / "config.json")
        monkeypatch.setenv("MY_CFG", path)
        r: ConcreteRestorer = make_restorer(env_var="MY_CFG")
        assert r.get_file_path() == path

    def test_get_file_path_empty_string_triggers_env_var_lookup(self, tmp_path: Path,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty string file_reference triggers env var lookup, same as None."""
        path: str = str(tmp_path / "config.json")
        monkeypatch.setenv("MY_CFG", path)
        r: ConcreteRestorer = make_restorer(env_var="MY_CFG")
        assert r.get_file_path("") == path

    def test_get_file_path_returns_none_when_no_reference_and_no_env_var(self) -> None:
        """None is returned when neither a file_reference nor an env var is set."""
        r: ConcreteRestorer = make_restorer()
        assert r.get_file_path() is None

    def test_get_file_path_falls_back_to_deprecated_env_var(self, tmp_path: Path,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
        """When env_var is unset, the deprecated_env_var value is used."""
        path: str = str(tmp_path / "config.json")
        monkeypatch.delenv("NEW_VAR", raising=False)
        monkeypatch.setenv("OLD_VAR", path)
        r: ConcreteRestorer = make_restorer(env_var="NEW_VAR", deprecated_env_var="OLD_VAR")
        assert r.get_file_path() == path

    def test_get_file_path_logs_warning_when_deprecated_env_var_used(self, tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch,
                                                                     caplog: pytest.LogCaptureFixture) -> None:
        """A WARNING is logged when the deprecated env var supplies the path."""
        path: str = str(tmp_path / "config.json")
        monkeypatch.delenv("NEW_VAR", raising=False)
        monkeypatch.setenv("OLD_VAR", path)
        r: ConcreteRestorer = make_restorer(env_var="NEW_VAR", deprecated_env_var="OLD_VAR")
        with caplog.at_level(logging.WARNING):
            r.get_file_path()
        assert "deprecated" in caplog.text.lower()

    def test_get_file_path_primary_env_var_takes_precedence_over_deprecated(self, tmp_path: Path,
                                                                            monkeypatch: pytest.MonkeyPatch) -> None:
        """env_var takes precedence over deprecated_env_var when both are set."""
        new_path: str = str(tmp_path / "new.json")
        old_path: str = str(tmp_path / "old.json")
        monkeypatch.setenv("NEW_VAR", new_path)
        monkeypatch.setenv("OLD_VAR", old_path)
        r: ConcreteRestorer = make_restorer(env_var="NEW_VAR", deprecated_env_var="OLD_VAR")
        assert r.get_file_path() == new_path

    def test_get_file_path_no_warning_logged_when_primary_env_var_used(self, tmp_path: Path,
                                                                       monkeypatch: pytest.MonkeyPatch,
                                                                       caplog: pytest.LogCaptureFixture) -> None:
        """No deprecation warning is logged when the primary env var is used."""
        monkeypatch.setenv("NEW_VAR", str(tmp_path / "new.json"))
        monkeypatch.setenv("OLD_VAR", str(tmp_path / "old.json"))
        r: ConcreteRestorer = make_restorer(env_var="NEW_VAR", deprecated_env_var="OLD_VAR")
        with caplog.at_level(logging.WARNING):
            r.get_file_path()
        assert "deprecated" not in caplog.text.lower()

    # -----------------------------------------------------------------------
    # deserialize_file_contents
    # -----------------------------------------------------------------------

    def test_deserialize_parses_valid_json(self) -> None:
        """Valid JSON content is deserialised to the expected dictionary."""
        r: ConcreteRestorer = make_restorer()
        result: Dict[str, Any] = r.deserialize_file_contents("config.json", VALID_JSON)
        assert result == VALID_DICT

    def test_deserialize_parses_valid_hocon(self) -> None:
        """Valid HOCON content is deserialised to the expected dictionary."""
        r: ConcreteRestorer = make_restorer()
        result: Dict[str, Any] = r.deserialize_file_contents("config.hocon", VALID_HOCON)
        assert result == VALID_DICT

    def test_deserialize_raises_value_error_for_unsupported_extension(self) -> None:
        """A ValueError is raised for file extensions other than .json and .hocon."""
        r: ConcreteRestorer = make_restorer()
        with pytest.raises(ValueError, match="must be a .json or .hocon file"):
            r.deserialize_file_contents("config.yaml", "{}")

    def test_deserialize_raises_parse_exception_on_invalid_json(self) -> None:
        """A ParseException is raised when JSON content is syntactically invalid."""
        r: ConcreteRestorer = make_restorer()
        with pytest.raises(ParseException):
            r.deserialize_file_contents("config.json", INVALID_JSON)

    def test_deserialize_raises_parse_exception_on_invalid_hocon(self) -> None:
        """A ParseException is raised when HOCON content is syntactically invalid."""
        r: ConcreteRestorer = make_restorer()
        with pytest.raises(ParseException):
            r.deserialize_file_contents("config.hocon", INVALID_HOCON)

    def test_deserialize_parse_exception_wraps_original(self) -> None:
        """The raised ParseException chains the original parsing error as its cause."""
        r: ConcreteRestorer = make_restorer()
        with pytest.raises(ParseException) as exc_info:
            r.deserialize_file_contents("config.json", INVALID_JSON)
        assert exc_info.value.__cause__ is not None

    # -----------------------------------------------------------------------
    # filter_config
    # -----------------------------------------------------------------------

    def test_filter_config_returns_config_unchanged_when_not_none(self, tmp_path: Path) -> None:
        """A non-None config is returned as-is without modification."""
        r: ConcreteRestorer = make_restorer()
        cfg: Dict[str, Any] = {"a": 1}
        assert r.filter_config(cfg, str(tmp_path / "config.json")) is cfg

    def test_filter_config_file_path_is_optional(self) -> None:
        """filter_config can be called without a file_path argument."""
        r: ConcreteRestorer = make_restorer(must_exist=False)
        assert r.filter_config({"x": 1}) == {"x": 1}

    def test_filter_config_returns_none_when_must_exist_false_and_config_is_none(self, tmp_path: Path) -> None:
        """None is returned silently when must_exist is False and config is None."""
        r: ConcreteRestorer = make_restorer(must_exist=False)
        assert r.filter_config(None, str(tmp_path / "missing.json")) is None

    def test_filter_config_raises_file_not_found_when_must_exist_and_config_is_none(self, tmp_path: Path) -> None:
        """A FileNotFoundError is raised when must_exist is True and config is None."""
        r: ConcreteRestorer = make_restorer(must_exist=True)
        with pytest.raises(FileNotFoundError):
            r.filter_config(None, str(tmp_path / "missing.json"))

    def test_filter_config_error_message_includes_file_path(self, tmp_path: Path) -> None:
        """The FileNotFoundError message contains the missing file path."""
        missing: str = str(tmp_path / "missing.json")
        r: ConcreteRestorer = make_restorer(must_exist=True)
        with pytest.raises(FileNotFoundError, match="missing.json"):
            r.filter_config(None, missing)

    def test_filter_config_error_message_includes_env_var(self, tmp_path: Path) -> None:
        """The FileNotFoundError message includes the env_var name."""
        r: ConcreteRestorer = make_restorer(env_var="MY_VAR", must_exist=True)
        with pytest.raises(FileNotFoundError, match="MY_VAR"):
            r.filter_config(None, str(tmp_path / "missing.json"))

    def test_filter_config_error_message_includes_both_env_vars(self, tmp_path: Path) -> None:
        """The FileNotFoundError message includes both env_var and deprecated_env_var names."""
        r: ConcreteRestorer = make_restorer(env_var="NEW_VAR", deprecated_env_var="OLD_VAR", must_exist=True)
        with pytest.raises(FileNotFoundError) as exc_info:
            r.filter_config(None, str(tmp_path / "missing.json"))
        assert "NEW_VAR" in str(exc_info.value)
        assert "OLD_VAR" in str(exc_info.value)

    # -----------------------------------------------------------------------
    # restore (synchronous)
    # -----------------------------------------------------------------------

    def test_restore_returns_none_when_no_file_path(self) -> None:
        """None is returned when no file path can be resolved."""
        r: ConcreteRestorer = make_restorer(must_exist=False)
        assert r.restore() is None

    def test_restore_reads_json_file(self, tmp_path: Path) -> None:
        """A valid JSON file on disk is read and deserialised correctly."""
        path: str = write_json_file(tmp_path, {"key": "value"})
        r: ConcreteRestorer = make_restorer()
        assert r.restore(path) == {"key": "value"}

    def test_restore_reads_hocon_file(self, tmp_path: Path) -> None:
        """A valid HOCON file on disk is read and deserialised correctly."""
        path: str = write_hocon_file(tmp_path, VALID_HOCON)
        r: ConcreteRestorer = make_restorer()
        assert r.restore(path) == VALID_DICT

    def test_restore_swallows_file_not_found_when_must_exist_false(self, tmp_path: Path) -> None:
        """A missing file is silently ignored and None is returned when must_exist is False."""
        r: ConcreteRestorer = make_restorer(must_exist=False)
        assert r.restore(str(tmp_path / "nonexistent.json")) is None

    def test_restore_raises_file_not_found_when_must_exist_true(self, tmp_path: Path) -> None:
        """A FileNotFoundError is raised for a missing file when must_exist is True."""
        r: ConcreteRestorer = make_restorer(must_exist=True)
        with pytest.raises(FileNotFoundError):
            r.restore(str(tmp_path / "nonexistent.json"))

    def test_restore_uses_env_var_when_no_explicit_reference(self, tmp_path: Path,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
        """When no explicit file_reference is given, the env_var path is used."""
        path: str = write_json_file(tmp_path, {"key": "value"})
        monkeypatch.setenv("MY_CFG", path)
        r: ConcreteRestorer = make_restorer(env_var="MY_CFG")
        assert r.restore()["key"] == "value"

    def test_restore_calls_filter_config(self, tmp_path: Path) -> None:
        """filter_config is called exactly once per restore invocation."""
        path: str = write_json_file(tmp_path, {"key": "value"})
        r: ConcreteRestorer = make_restorer()
        with patch.object(r, "filter_config", wraps=r.filter_config) as mock_filter:
            r.restore(path)
        mock_filter.assert_called_once()

    def test_restore_raises_parse_exception_on_malformed_json(self, tmp_path: Path) -> None:
        """A ParseException is raised when a .json file contains invalid content."""
        path: str = write_json_file(tmp_path, {})
        Path(path).write_text(INVALID_JSON, encoding="utf-8")
        r: ConcreteRestorer = make_restorer()
        with pytest.raises(ParseException):
            r.restore(path)

    def test_restore_raises_parse_exception_on_malformed_hocon(self, tmp_path: Path) -> None:
        """A ParseException is raised when a .hocon file contains invalid content."""
        path: str = write_hocon_file(tmp_path, INVALID_HOCON)
        r: ConcreteRestorer = make_restorer()
        with pytest.raises(ParseException):
            r.restore(path)

    def test_restore_raises_value_error_on_unsupported_extension(self, tmp_path: Path) -> None:
        """A ValueError is raised when the file has an unsupported extension."""
        path: Path = tmp_path / "config.yaml"
        path.write_text("key: value", encoding="utf-8")
        r: ConcreteRestorer = make_restorer()
        with pytest.raises(ValueError):
            r.restore(str(path))

    # -----------------------------------------------------------------------
    # async_restore
    # -----------------------------------------------------------------------

    def test_async_restore_returns_none_when_no_file_path(self) -> None:
        """None is returned when no file path can be resolved."""
        r: ConcreteRestorer = make_restorer(must_exist=False)
        assert run(r.async_restore()) is None

    def test_async_restore_reads_json_file(self) -> None:
        """A valid JSON payload read asynchronously is deserialised correctly."""
        r: ConcreteRestorer = make_restorer()
        ctx: MagicMock = self._make_async_open_ctx(VALID_JSON)
        with patch("neuro_san.internals.persistence.abstract_async_config_restorer.async_open", return_value=ctx):
            result: Dict[str, Any] = run(r.async_restore("config.json"))
        assert result == VALID_DICT

    def test_async_restore_reads_hocon_file(self) -> None:
        """A valid HOCON payload read asynchronously is deserialised correctly."""
        r: ConcreteRestorer = make_restorer()
        ctx: MagicMock = self._make_async_open_ctx(VALID_HOCON)
        with patch("neuro_san.internals.persistence.abstract_async_config_restorer.async_open", return_value=ctx):
            result: Dict[str, Any] = run(r.async_restore("config.hocon"))
        assert result == VALID_DICT

    def test_async_restore_swallows_file_not_found_when_must_exist_false(self) -> None:
        """A missing file is silently ignored and None is returned when must_exist is False."""
        r: ConcreteRestorer = make_restorer(must_exist=False)
        with patch("neuro_san.internals.persistence.abstract_async_config_restorer.async_open",
                   return_value=self._make_async_open_ctx_missing()):
            assert run(r.async_restore("config.json")) is None

    def test_async_restore_raises_file_not_found_when_must_exist_true(self) -> None:
        """A FileNotFoundError is raised for a missing file when must_exist is True."""
        r: ConcreteRestorer = make_restorer(must_exist=True)
        with patch("neuro_san.internals.persistence.abstract_async_config_restorer.async_open",
                   return_value=self._make_async_open_ctx_missing()):
            with pytest.raises(FileNotFoundError):
                run(r.async_restore("config.json"))

    def test_async_restore_calls_filter_config(self) -> None:
        """filter_config is called exactly once per async_restore invocation."""
        r: ConcreteRestorer = make_restorer()
        ctx: MagicMock = self._make_async_open_ctx(VALID_JSON)
        with patch("neuro_san.internals.persistence.abstract_async_config_restorer.async_open", return_value=ctx):
            with patch.object(r, "filter_config", wraps=r.filter_config) as mock_filter:
                run(r.async_restore("config.json"))
        mock_filter.assert_called_once()

    def test_async_restore_uses_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When no explicit file_reference is given, the env_var path is used."""
        path: str = str(tmp_path / "config.json")
        monkeypatch.setenv("MY_CFG", path)
        r: ConcreteRestorer = make_restorer(env_var="MY_CFG")
        ctx: MagicMock = self._make_async_open_ctx(VALID_JSON)
        with patch("neuro_san.internals.persistence.abstract_async_config_restorer.async_open", return_value=ctx):
            result: Dict[str, Any] = run(r.async_restore())
        assert result["key"] == "value"

    def test_async_restore_raises_parse_exception_on_malformed_json(self) -> None:
        """A ParseException is raised when an async-read .json payload is invalid."""
        r: ConcreteRestorer = make_restorer()
        ctx: MagicMock = self._make_async_open_ctx(INVALID_JSON)
        with patch("neuro_san.internals.persistence.abstract_async_config_restorer.async_open", return_value=ctx):
            with pytest.raises(ParseException):
                run(r.async_restore("config.json"))

    def test_async_restore_raises_parse_exception_on_malformed_hocon(self) -> None:
        """A ParseException is raised when an async-read .hocon payload is invalid."""
        r: ConcreteRestorer = make_restorer()
        ctx: MagicMock = self._make_async_open_ctx(INVALID_HOCON)
        with patch("neuro_san.internals.persistence.abstract_async_config_restorer.async_open", return_value=ctx):
            with pytest.raises(ParseException):
                run(r.async_restore("config.hocon"))
