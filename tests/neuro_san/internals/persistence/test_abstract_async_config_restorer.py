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
import shutil
from pathlib import Path
from typing import Any
from typing import Awaitable
from typing import Dict
from typing import TypeVar
from unittest.mock import patch

import pytest

from neuro_san.internals.persistence.abstract_async_config_restorer import AbstractAsyncConfigRestorer

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Concrete subclass used by all tests.
# AbstractAsyncConfigRestorer inherits from abstract base
# classes. ConcreteRestorer makes the test intent explicit at no cost.
# ---------------------------------------------------------------------------


class ConcreteRestorer(AbstractAsyncConfigRestorer):
    """Minimal concrete subclass – inherits all behaviour from the abstract base."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_DICT: Dict[str, Any] = {"key": "value", "nested": {"a": 1}}

# Directory containing .json and .hocon fixture files used by the tests.
FIXTURES_DIR: Path = Path(__file__).parent.parent.parent.parent / "fixtures"


# pylint: disable=too-many-public-methods
class TestAbstractAsyncConfigRestorer:
    """
    Tests for AbstractAsyncConfigRestorer covering __init__, get_file_path,
    deserialize_file_contents, filter_config, restore, and async_restore.
    """

    # -----------------------------------------------------------------------
    # Class-level helpers
    # -----------------------------------------------------------------------

    @staticmethod
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

    @staticmethod
    def run(coro: Awaitable[T]) -> T:
        """Run an awaitable to completion using asyncio.run."""
        return asyncio.run(coro)

    @staticmethod
    def write_json_file(tmp_path: Path, content: Dict[str, Any], filename: str = "config.json") -> str:
        """Write a JSON-serialised dict to a temporary file and return its path."""
        path: Path = tmp_path / filename
        path.write_text(json.dumps(content), encoding="utf-8")
        return str(path)

    @staticmethod
    def write_hocon_file(tmp_path: Path, content: str, filename: str = "config.hocon") -> str:
        """Write raw HOCON content to a temporary file and return its path."""
        path: Path = tmp_path / filename
        path.write_text(content, encoding="utf-8")
        return str(path)

    @staticmethod
    def copy_fixture(tmp_path: Path, fixture_name: str) -> str:
        """Copy a fixture file into tmp_path and return its path."""
        src: Path = FIXTURES_DIR / fixture_name
        dst: Path = tmp_path / fixture_name
        shutil.copy(src, dst)
        return str(dst)

    # -----------------------------------------------------------------------
    # __init__
    # -----------------------------------------------------------------------

    def test_stores_all_constructor_args(self) -> None:
        """All constructor arguments are stored as instance attributes."""
        r: ConcreteRestorer = ConcreteRestorer(
            "my file", env_var="MY_VAR", must_exist=False, deprecated_env_var="OLD_VAR")
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
        r: ConcreteRestorer = self.make_restorer()
        assert r.get_file_path(path) == path

    def test_get_file_path_falls_back_to_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When no file_reference is given, the value of env_var is used."""
        path: str = str(tmp_path / "config.json")
        monkeypatch.setenv("MY_CFG", path)
        r: ConcreteRestorer = self.make_restorer(env_var="MY_CFG")
        assert r.get_file_path() == path

    def test_get_file_path_empty_string_triggers_env_var_lookup(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty string file_reference triggers env var lookup, same as None."""
        path: str = str(tmp_path / "config.json")
        monkeypatch.setenv("MY_CFG", path)
        r: ConcreteRestorer = self.make_restorer(env_var="MY_CFG")
        assert r.get_file_path("") == path

    def test_get_file_path_returns_none_when_no_reference_and_no_env_var(self) -> None:
        """None is returned when neither a file_reference nor an env var is set."""
        r: ConcreteRestorer = self.make_restorer()
        assert r.get_file_path() is None

    def test_get_file_path_falls_back_to_deprecated_env_var(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When env_var is unset, the deprecated_env_var value is used."""
        path: str = str(tmp_path / "config.json")
        monkeypatch.delenv("NEW_VAR", raising=False)
        monkeypatch.setenv("OLD_VAR", path)
        r: ConcreteRestorer = self.make_restorer(env_var="NEW_VAR", deprecated_env_var="OLD_VAR")
        assert r.get_file_path() == path

    def test_get_file_path_logs_warning_when_deprecated_env_var_used(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        """A WARNING is logged when the deprecated env var supplies the path."""
        path: str = str(tmp_path / "config.json")
        monkeypatch.delenv("NEW_VAR", raising=False)
        monkeypatch.setenv("OLD_VAR", path)
        r: ConcreteRestorer = self.make_restorer(env_var="NEW_VAR", deprecated_env_var="OLD_VAR")
        with caplog.at_level(logging.WARNING):
            r.get_file_path()
        assert "deprecated" in caplog.text.lower()

    def test_get_file_path_primary_env_var_takes_precedence_over_deprecated(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """env_var takes precedence over deprecated_env_var when both are set."""
        new_path: str = str(tmp_path / "new.json")
        old_path: str = str(tmp_path / "old.json")
        monkeypatch.setenv("NEW_VAR", new_path)
        monkeypatch.setenv("OLD_VAR", old_path)
        r: ConcreteRestorer = self.make_restorer(env_var="NEW_VAR", deprecated_env_var="OLD_VAR")
        assert r.get_file_path() == new_path

    def test_get_file_path_no_warning_logged_when_primary_env_var_used(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        """No deprecation warning is logged when the primary env var is used."""
        monkeypatch.setenv("NEW_VAR", str(tmp_path / "new.json"))
        monkeypatch.setenv("OLD_VAR", str(tmp_path / "old.json"))
        r: ConcreteRestorer = self.make_restorer(env_var="NEW_VAR", deprecated_env_var="OLD_VAR")
        with caplog.at_level(logging.WARNING):
            r.get_file_path()
        assert "deprecated" not in caplog.text.lower()

    # -----------------------------------------------------------------------
    # deserialize_file_contents
    # -----------------------------------------------------------------------

    def test_deserialize_parses_valid_json(self) -> None:
        """Valid JSON content is deserialised to the expected dictionary."""
        r: ConcreteRestorer = self.make_restorer()
        result: Dict[str, Any] = r.deserialize_file_contents(
            str(FIXTURES_DIR / "valid.json"),
            (FIXTURES_DIR / "valid.json").read_bytes(),
        )
        assert result == VALID_DICT

    def test_deserialize_parses_valid_hocon(self) -> None:
        """Valid HOCON content is deserialised to the expected dictionary."""
        r: ConcreteRestorer = self.make_restorer()
        result: Dict[str, Any] = r.deserialize_file_contents(
            str(FIXTURES_DIR / "valid.hocon"),
            (FIXTURES_DIR / "valid.hocon").read_bytes(),
        )
        assert result == VALID_DICT

    def test_deserialize_raises_value_error_for_unsupported_extension(self) -> None:
        """A ValueError is raised for file extensions other than .json and .hocon."""
        r: ConcreteRestorer = self.make_restorer()
        with pytest.raises(ValueError, match="must be a .json or .hocon file"):
            r.deserialize_file_contents("config.yaml", b'{}')

    def test_deserialize_raises_value_error_on_invalid_json(self) -> None:
        """A ValueError is raised when JSON content is syntactically invalid."""
        r: ConcreteRestorer = self.make_restorer()
        with pytest.raises(ValueError):
            r.deserialize_file_contents(
                str(FIXTURES_DIR / "invalid.json"),
                (FIXTURES_DIR / "invalid.json").read_bytes(),
            )

    def test_deserialize_raises_value_error_on_invalid_hocon(self) -> None:
        """A ValueError is raised when HOCON content is syntactically invalid."""
        r: ConcreteRestorer = self.make_restorer()
        with pytest.raises(ValueError):
            r.deserialize_file_contents(
                str(FIXTURES_DIR / "invalid.hocon"),
                (FIXTURES_DIR / "invalid.hocon").read_bytes(),
            )

    def test_deserialize_value_error_wraps_original(self) -> None:
        """The raised ValueError chains the original parsing error as its cause."""
        r: ConcreteRestorer = self.make_restorer()
        with pytest.raises(ValueError) as exc_info:
            r.deserialize_file_contents(
                str(FIXTURES_DIR / "invalid.json"),
                (FIXTURES_DIR / "invalid.json").read_bytes(),
            )
        assert exc_info.value.__cause__ is not None

    # -----------------------------------------------------------------------
    # filter_config
    # -----------------------------------------------------------------------

    def test_filter_config_returns_config_unchanged_when_not_none(self, tmp_path: Path) -> None:
        """A non-None config is returned with no semantic changes."""
        r: ConcreteRestorer = self.make_restorer()
        cfg: Dict[str, Any] = {"a": 1}
        assert r.filter_config(cfg, str(tmp_path / "config.json")) == cfg

    def test_filter_config_file_path_is_optional(self) -> None:
        """filter_config can be called without a file_path argument."""
        r: ConcreteRestorer = self.make_restorer(must_exist=False)
        assert r.filter_config({"x": 1}) == {"x": 1}

    def test_filter_config_returns_none_when_must_exist_false_and_config_is_none(self, tmp_path: Path) -> None:
        """None is returned silently when must_exist is False and config is None."""
        r: ConcreteRestorer = self.make_restorer(must_exist=False)
        assert r.filter_config(None, str(tmp_path / "missing.json")) is None

    def test_filter_config_raises_file_not_found_when_must_exist_and_config_is_none(self, tmp_path: Path) -> None:
        """A FileNotFoundError is raised when must_exist is True and config is None."""
        r: ConcreteRestorer = self.make_restorer(must_exist=True)
        with pytest.raises(FileNotFoundError):
            r.filter_config(None, str(tmp_path / "missing.json"))

    def test_filter_config_error_message_includes_file_path(self, tmp_path: Path) -> None:
        """The FileNotFoundError message contains the missing file path."""
        missing: str = str(tmp_path / "missing.json")
        r: ConcreteRestorer = self.make_restorer(must_exist=True)
        with pytest.raises(FileNotFoundError, match="missing.json"):
            r.filter_config(None, missing)

    def test_filter_config_error_message_includes_env_var(self, tmp_path: Path) -> None:
        """The FileNotFoundError message includes the env_var name."""
        r: ConcreteRestorer = self.make_restorer(env_var="MY_VAR", must_exist=True)
        with pytest.raises(FileNotFoundError, match="MY_VAR"):
            r.filter_config(None, str(tmp_path / "missing.json"))

    def test_filter_config_error_message_includes_both_env_vars(self, tmp_path: Path) -> None:
        """The FileNotFoundError message includes both env_var and deprecated_env_var names."""
        r: ConcreteRestorer = self.make_restorer(env_var="NEW_VAR", deprecated_env_var="OLD_VAR", must_exist=True)
        with pytest.raises(FileNotFoundError) as exc_info:
            r.filter_config(None, str(tmp_path / "missing.json"))
        assert "NEW_VAR" in str(exc_info.value)
        assert "OLD_VAR" in str(exc_info.value)

    # -----------------------------------------------------------------------
    # restore (synchronous)
    # -----------------------------------------------------------------------

    def test_restore_returns_none_when_no_file_path(self) -> None:
        """None is returned when no file path can be resolved."""
        r: ConcreteRestorer = self.make_restorer(must_exist=False)
        assert r.restore() is None

    def test_restore_reads_json_file(self, tmp_path: Path) -> None:
        """A valid JSON file on disk is read and deserialised correctly."""
        path: str = self.copy_fixture(tmp_path, "valid.json")
        r: ConcreteRestorer = self.make_restorer()
        assert r.restore(path) == VALID_DICT

    def test_restore_reads_hocon_file(self, tmp_path: Path) -> None:
        """A valid HOCON file on disk is read and deserialised correctly."""
        path: str = self.copy_fixture(tmp_path, "valid.hocon")
        r: ConcreteRestorer = self.make_restorer()
        assert r.restore(path) == VALID_DICT

    def test_restore_swallows_file_not_found_when_must_exist_false(self, tmp_path: Path) -> None:
        """A missing file is silently ignored and None is returned when must_exist is False."""
        r: ConcreteRestorer = self.make_restorer(must_exist=False)
        assert r.restore(str(tmp_path / "nonexistent.json")) is None

    def test_restore_raises_file_not_found_when_must_exist_true(self, tmp_path: Path) -> None:
        """A FileNotFoundError is raised for a missing file when must_exist is True."""
        r: ConcreteRestorer = self.make_restorer(must_exist=True)
        with pytest.raises(FileNotFoundError):
            r.restore(str(tmp_path / "nonexistent.json"))

    def test_restore_uses_env_var_when_no_explicit_reference(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When no explicit file_reference is given, the env_var path is used."""
        path: str = self.copy_fixture(tmp_path, "valid.json")
        monkeypatch.setenv("MY_CFG", path)
        r: ConcreteRestorer = self.make_restorer(env_var="MY_CFG")
        assert r.restore()["key"] == "value"

    def test_restore_calls_filter_config(self, tmp_path: Path) -> None:
        """filter_config is called exactly once per restore invocation."""
        path: str = self.copy_fixture(tmp_path, "valid.json")
        r: ConcreteRestorer = self.make_restorer()
        with patch.object(r, "filter_config", wraps=r.filter_config) as mock_filter:
            r.restore(path)
        mock_filter.assert_called_once()

    def test_restore_raises_value_error_on_malformed_json(self, tmp_path: Path) -> None:
        """A ValueError is raised when a .json file contains invalid content."""
        path: str = self.copy_fixture(tmp_path, "invalid.json")
        r: ConcreteRestorer = self.make_restorer()
        with pytest.raises(ValueError):
            r.restore(path)

    def test_restore_raises_value_error_on_malformed_hocon(self, tmp_path: Path) -> None:
        """A ValueError is raised when a .hocon file contains invalid content."""
        path: str = self.copy_fixture(tmp_path, "invalid.hocon")
        r: ConcreteRestorer = self.make_restorer()
        with pytest.raises(ValueError):
            r.restore(path)

    def test_restore_raises_value_error_on_unsupported_extension(self, tmp_path: Path) -> None:
        """A ValueError is raised when the file has an unsupported extension."""
        path: Path = tmp_path / "config.yaml"
        path.write_text("key: value", encoding="utf-8")
        r: ConcreteRestorer = self.make_restorer()
        with pytest.raises(ValueError):
            r.restore(str(path))

    # -----------------------------------------------------------------------
    # async_restore
    # -----------------------------------------------------------------------

    def test_async_restore_returns_none_when_no_file_path(self) -> None:
        """None is returned when no file path can be resolved."""
        r: ConcreteRestorer = self.make_restorer(must_exist=False)
        assert self.run(r.async_restore()) is None

    def test_async_restore_reads_json_file(self, tmp_path: Path) -> None:
        """A valid JSON file read asynchronously is deserialised correctly."""
        path: str = self.copy_fixture(tmp_path, "valid.json")
        r: ConcreteRestorer = self.make_restorer()
        assert self.run(r.async_restore(path)) == VALID_DICT

    def test_async_restore_reads_hocon_file(self, tmp_path: Path) -> None:
        """A valid HOCON file read asynchronously is deserialised correctly."""
        path: str = self.copy_fixture(tmp_path, "valid.hocon")
        r: ConcreteRestorer = self.make_restorer()
        assert self.run(r.async_restore(path)) == VALID_DICT

    def test_async_restore_swallows_file_not_found_when_must_exist_false(self, tmp_path: Path) -> None:
        """A missing file is silently ignored and None is returned when must_exist is False."""
        r: ConcreteRestorer = self.make_restorer(must_exist=False)
        assert self.run(r.async_restore(str(tmp_path / "nonexistent.json"))) is None

    def test_async_restore_raises_file_not_found_when_must_exist_true(self, tmp_path: Path) -> None:
        """A FileNotFoundError is raised for a missing file when must_exist is True."""
        r: ConcreteRestorer = self.make_restorer(must_exist=True)
        with pytest.raises(FileNotFoundError):
            self.run(r.async_restore(str(tmp_path / "nonexistent.json")))

    def test_async_restore_calls_filter_config(self, tmp_path: Path) -> None:
        """filter_config is called exactly once per async_restore invocation."""
        path: str = self.copy_fixture(tmp_path, "valid.json")
        r: ConcreteRestorer = self.make_restorer()
        with patch.object(r, "filter_config", wraps=r.filter_config) as mock_filter:
            self.run(r.async_restore(path))
        mock_filter.assert_called_once()

    def test_async_restore_uses_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When no explicit file_reference is given, the env_var path is used."""
        path: str = self.copy_fixture(tmp_path, "valid.json")
        monkeypatch.setenv("MY_CFG", path)
        r: ConcreteRestorer = self.make_restorer(env_var="MY_CFG")
        assert self.run(r.async_restore())["key"] == "value"

    def test_async_restore_raises_value_error_on_malformed_json(self, tmp_path: Path) -> None:
        """A ValueError is raised when an async-read .json file is invalid."""
        path: str = self.copy_fixture(tmp_path, "invalid.json")
        r: ConcreteRestorer = self.make_restorer()
        with pytest.raises(ValueError):
            self.run(r.async_restore(path))

    def test_async_restore_raises_value_error_on_malformed_hocon(self, tmp_path: Path) -> None:
        """A ValueError is raised when an async-read .hocon file is invalid."""
        path: str = self.copy_fixture(tmp_path, "invalid.hocon")
        r: ConcreteRestorer = self.make_restorer()
        with pytest.raises(ValueError):
            self.run(r.async_restore(path))

    # -----------------------------------------------------------------------
    # deserialize_file_contents caching (NEURO_SAN_PARSE_CACHE)
    # -----------------------------------------------------------------------

    @pytest.fixture(autouse=True)
    def clear_deserialization_cache(self):
        """
        The cache is a class-level dict shared by every AbstractAsyncConfigRestorer
        subclass/instance, so tests that opt into it must not leak entries to
        (or inherit entries from) any other test.
        """
        # pylint: disable=protected-access
        AbstractAsyncConfigRestorer._deserialization_cache.clear()
        yield
        AbstractAsyncConfigRestorer._deserialization_cache.clear()

    def test_cache_hit_returns_a_copy_not_the_cached_object(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        A caller that mutates what deserialize_file_contents() gives it back must
        not corrupt what a later cache hit for the same key returns.
        """
        monkeypatch.setenv("NEURO_SAN_PARSE_CACHE", "1")
        path: str = self.write_hocon_file(tmp_path, 'key = "value"\nnested { a = 1 }\n')
        contents: bytes = Path(path).read_bytes()
        r: ConcreteRestorer = self.make_restorer()

        first: Dict[str, Any] = r.deserialize_file_contents(path, contents)
        first["nested"]["a"] = "mutated in place"

        second: Dict[str, Any] = r.deserialize_file_contents(path, contents)
        assert second["nested"]["a"] == 1
        assert second is not first

    def test_cache_hit_returns_equivalent_config_without_reparsing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A cache hit still returns a dict equal to what a fresh parse would produce."""
        monkeypatch.setenv("NEURO_SAN_PARSE_CACHE", "1")
        path: str = self.copy_fixture(tmp_path, "valid.hocon")
        contents: bytes = Path(path).read_bytes()
        r: ConcreteRestorer = self.make_restorer()

        first: Dict[str, Any] = r.deserialize_file_contents(path, contents)
        second: Dict[str, Any] = r.deserialize_file_contents(path, contents)
        assert first == VALID_DICT
        assert second == VALID_DICT

    def test_cache_disabled_by_default_still_reparses_correctly(self, tmp_path: Path) -> None:
        """With the env var unset, repeated calls just reparse - no caching, no crash."""
        path: str = self.copy_fixture(tmp_path, "valid.hocon")
        contents: bytes = Path(path).read_bytes()
        r: ConcreteRestorer = self.make_restorer()

        first: Dict[str, Any] = r.deserialize_file_contents(path, contents)
        first["nested"]["a"] = "mutated in place"

        second: Dict[str, Any] = r.deserialize_file_contents(path, contents)
        assert second["nested"]["a"] == 1

    def test_cache_evicts_least_recently_used_beyond_max_entries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The cache does not grow without bound across many distinct file versions."""
        monkeypatch.setenv("NEURO_SAN_PARSE_CACHE", "1")
        monkeypatch.setattr(
            "neuro_san.internals.persistence.abstract_async_config_restorer._CACHE_MAX_ENTRIES", 3
        )
        r: ConcreteRestorer = self.make_restorer()

        # Five distinct file contents -> five distinct cache keys, cap is 3.
        for i in range(5):
            path: str = self.write_hocon_file(tmp_path, f'key = "value{i}"\n', filename=f"config{i}.hocon")
            r.deserialize_file_contents(path, Path(path).read_bytes())

        # pylint: disable=protected-access
        assert len(AbstractAsyncConfigRestorer._deserialization_cache) == 3
