
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
Unit tests for build_scripts/build_neuro_san_lite.py.

These tests are the forcing function for the forcing function: if the lint
stops catching forbidden imports, these tests fail.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make build_scripts importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from build_scripts import build_neuro_san_lite as bnl


@pytest.fixture
def good_file(tmp_path: Path) -> Path:
    """A module that uses only allowed imports."""
    p = tmp_path / "good.py"
    p.write_text(
        "from __future__ import annotations\n"
        "import json\n"
        "import hashlib\n"
        "from typing import Any\n"
        "from urllib.parse import urlparse\n"
        "import httpx\n"
        "\n"
        "def hello() -> str:\n"
        "    return 'hi'\n"
    )
    return p


@pytest.fixture
def aiohttp_file(tmp_path: Path) -> Path:
    """A module that imports a forbidden HTTP client."""
    p = tmp_path / "bad_aiohttp.py"
    p.write_text(
        "import aiohttp\n"
        "from aiohttp import ClientSession\n"
        "\n"
        "async def fetch():\n"
        "    pass\n"
    )
    return p


@pytest.fixture
def langchain_file(tmp_path: Path) -> Path:
    p = tmp_path / "bad_langchain.py"
    p.write_text(
        "from langchain_anthropic import ChatAnthropic\n"
        "from langchain_core.messages import AIMessage\n"
    )
    return p


@pytest.fixture
def relative_import_file(tmp_path: Path) -> Path:
    """Relative imports inside the package must always be allowed."""
    p = tmp_path / "rel.py"
    p.write_text(
        "from . import wire_config\n"
        "from .redactor import SlyDataRedactor\n"
        "from .. import shared\n"
    )
    return p


@pytest.fixture
def own_package_file(tmp_path: Path) -> Path:
    p = tmp_path / "own.py"
    p.write_text(
        "from neuro_san_client.wire_config import verify_wire_config\n"
        "import neuro_san_client\n"
    )
    return p


@pytest.fixture
def syntax_error_file(tmp_path: Path) -> Path:
    p = tmp_path / "broken.py"
    p.write_text("def hello(  :\n    pass\n")
    return p


# ------------ tests ------------


class TestImportAllowed:
    def test_empty_returns_true(self):
        assert bnl._import_is_allowed("", set())

    def test_exact_match(self):
        assert bnl._import_is_allowed("httpx", {"httpx"})

    def test_top_level_match(self):
        assert bnl._import_is_allowed("urllib.parse", {"urllib.parse"})
        assert bnl._import_is_allowed("urllib.parse", {"urllib"})

    def test_own_package_is_allowed(self):
        assert bnl._import_is_allowed("neuro_san_client.foo", set())
        assert bnl._import_is_allowed("neuro_san_client", set())

    def test_forbidden(self):
        assert not bnl._import_is_allowed("aiohttp", {"httpx"})
        assert not bnl._import_is_allowed("langchain_core", {"httpx"})


class TestCheckImportsInFile:
    def test_good_file_has_no_errors(self, good_file: Path):
        assert bnl._check_imports_in_file(good_file) == []

    def test_aiohttp_is_caught(self, aiohttp_file: Path):
        errors = bnl._check_imports_in_file(aiohttp_file)
        # 'import aiohttp' (line 1) + 'from aiohttp import ...' (line 2)
        assert len(errors) == 2
        assert all("aiohttp" in e for e in errors)
        assert "bad_aiohttp.py:1:" in errors[0]
        assert "bad_aiohttp.py:2:" in errors[1]

    def test_langchain_is_caught(self, langchain_file: Path):
        errors = bnl._check_imports_in_file(langchain_file)
        assert len(errors) == 2
        assert all("langchain" in e for e in errors)

    def test_relative_imports_are_allowed(self, relative_import_file: Path):
        # Relative imports never check against the allowlist.
        assert bnl._check_imports_in_file(relative_import_file) == []

    def test_own_package_imports_are_allowed(self, own_package_file: Path):
        assert bnl._check_imports_in_file(own_package_file) == []

    def test_syntax_error_reported(self, syntax_error_file: Path):
        errors = bnl._check_imports_in_file(syntax_error_file)
        assert len(errors) == 1
        assert "syntax error" in errors[0]

    def test_test_files_get_extra_allowances(self, tmp_path: Path):
        # Path with "tests/" gets the extra allowlist.
        nested = tmp_path / "tests" / "test_x.py"
        nested.parent.mkdir()
        nested.write_text(
            "import pytest\n"
            "from unittest.mock import AsyncMock\n"
            "import pytest_asyncio\n"
        )
        assert bnl._check_imports_in_file(nested) == []

    def test_non_test_files_dont_get_test_allowances(self, tmp_path: Path):
        nontest = tmp_path / "mymodule.py"
        nontest.write_text("import pytest\n")  # only allowed in tests/
        errors = bnl._check_imports_in_file(nontest)
        assert len(errors) == 1
        assert "pytest" in errors[0]


class TestModulePairing:
    def test_missing_ts_module_is_reported(self, tmp_path: Path, monkeypatch):
        # Set up two trees where Python has an extra module.
        py_src = tmp_path / "py" / "neuro_san_client"
        py_src.mkdir(parents=True)
        (py_src / "__init__.py").write_text("")
        (py_src / "wire_config.py").write_text("")
        (py_src / "extra.py").write_text("")
        ts_src = tmp_path / "ts" / "src"
        ts_src.mkdir(parents=True)
        (ts_src / "wire_config.ts").write_text("")

        monkeypatch.setattr(bnl, "PY_PKG_SRC", py_src)
        monkeypatch.setattr(bnl, "TS_SRC", ts_src)
        rc = bnl.check_module_pairing(verbose=False)
        assert rc != 0

    def test_missing_py_module_is_reported(self, tmp_path: Path, monkeypatch):
        py_src = tmp_path / "py" / "neuro_san_client"
        py_src.mkdir(parents=True)
        (py_src / "__init__.py").write_text("")
        (py_src / "wire_config.py").write_text("")
        ts_src = tmp_path / "ts" / "src"
        ts_src.mkdir(parents=True)
        (ts_src / "wire_config.ts").write_text("")
        (ts_src / "extra.ts").write_text("")  # has no Python counterpart

        monkeypatch.setattr(bnl, "PY_PKG_SRC", py_src)
        monkeypatch.setattr(bnl, "TS_SRC", ts_src)
        rc = bnl.check_module_pairing(verbose=False)
        assert rc != 0

    def test_index_and_types_ts_are_exempt(self, tmp_path: Path, monkeypatch):
        # neuro-san-lite-js/src/index.ts and types.ts have no Python counterpart;
        # they are bundler entry points / type shims, not protocol modules.
        py_src = tmp_path / "py" / "neuro_san_client"
        py_src.mkdir(parents=True)
        (py_src / "__init__.py").write_text("")
        (py_src / "wire_config.py").write_text("")
        ts_src = tmp_path / "ts" / "src"
        ts_src.mkdir(parents=True)
        (ts_src / "wire_config.ts").write_text("")
        (ts_src / "index.ts").write_text("")
        (ts_src / "types.ts").write_text("")

        monkeypatch.setattr(bnl, "PY_PKG_SRC", py_src)
        monkeypatch.setattr(bnl, "TS_SRC", ts_src)
        assert bnl.check_module_pairing(verbose=False) == 0

    def test_clean_pairing_passes(self, tmp_path: Path, monkeypatch):
        py_src = tmp_path / "py" / "neuro_san_client"
        py_src.mkdir(parents=True)
        (py_src / "__init__.py").write_text("")
        (py_src / "wire_config.py").write_text("")
        (py_src / "redactor.py").write_text("")
        ts_src = tmp_path / "ts" / "src"
        ts_src.mkdir(parents=True)
        (ts_src / "wire_config.ts").write_text("")
        (ts_src / "redactor.ts").write_text("")

        monkeypatch.setattr(bnl, "PY_PKG_SRC", py_src)
        monkeypatch.setattr(bnl, "TS_SRC", ts_src)
        assert bnl.check_module_pairing(verbose=False) == 0


class TestLintPython:
    def test_clean_package_passes(self, tmp_path: Path, monkeypatch):
        py_src = tmp_path / "neuro-san-client" / "src" / "neuro_san_client"
        py_src.mkdir(parents=True)
        (py_src / "__init__.py").write_text("")
        (py_src / "wire_config.py").write_text(
            "import json\nfrom typing import Any\n"
        )
        tests_dir = tmp_path / "neuro-san-client" / "tests"
        tests_dir.mkdir(parents=True)

        monkeypatch.setattr(bnl, "PY_PKG_SRC", py_src)
        monkeypatch.setattr(bnl, "REPO_ROOT", tmp_path)
        assert bnl.lint_python(verbose=False) == 0

    def test_forbidden_package_fails(self, tmp_path: Path, monkeypatch):
        py_src = tmp_path / "neuro-san-client" / "src" / "neuro_san_client"
        py_src.mkdir(parents=True)
        (py_src / "__init__.py").write_text("")
        (py_src / "bad.py").write_text("import aiohttp\n")
        tests_dir = tmp_path / "neuro-san-client" / "tests"
        tests_dir.mkdir(parents=True)

        monkeypatch.setattr(bnl, "PY_PKG_SRC", py_src)
        monkeypatch.setattr(bnl, "REPO_ROOT", tmp_path)
        assert bnl.lint_python(verbose=False) != 0
