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
from pathlib import Path
from typing import Awaitable, TypeVar

import pytest

from neuro_san.internals.utils.text_file_reader import TextFileReader

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Encoding fixtures
#
# BytesDecoder tries the encodings utf-8, cp1252, latin-1 in that order and
# returns as soon as one succeeds. The byte sequences below are chosen so
# that each encoding's branch is exercised exactly once:
#
#   * utf-8     : valid UTF-8 multibyte sequence (E2 80 99 -> U+2019)
#   * cp1252    : 0x92 -- invalid as standalone UTF-8, valid in cp1252 (U+2019)
#   * latin-1   : 0x81 -- invalid in UTF-8 *and* in strict cp1252, valid in latin-1 (U+0081)
# ---------------------------------------------------------------------------

UTF8_BYTES: bytes = "hello ’world’".encode("utf-8")
UTF8_EXPECTED: str = "hello ’world’"

CP1252_BYTES: bytes = b"hello \x92world\x92"
CP1252_EXPECTED: str = "hello ’world’"

LATIN1_BYTES: bytes = b"hello \x81world\x81"
LATIN1_EXPECTED: str = "hello \u0081world\u0081"


class TestTextFileReader:
    """
    Tests for TextFileReader.read_text_file and TextFileReader.async_read_text_file
    covering all three encodings tried by BytesDecoder (utf-8, cp1252, latin-1).
    """

    # -----------------------------------------------------------------------
    # Class-level helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def run(coro: Awaitable[T]) -> T:
        """Run an awaitable to completion using asyncio.run."""
        return asyncio.run(coro)

    @staticmethod
    def write_bytes(tmp_path: Path, content: bytes, filename: str = "sample.txt") -> str:
        """Write raw bytes to a temporary file and return its path."""
        path: Path = tmp_path / filename
        path.write_bytes(content)
        return str(path)

    # -----------------------------------------------------------------------
    # read_text_file (synchronous)
    # -----------------------------------------------------------------------

    def test_read_text_file_decodes_utf8(self, tmp_path: Path) -> None:
        """A UTF-8 encoded file is decoded via the utf-8 branch."""
        path: str = self.write_bytes(tmp_path, UTF8_BYTES)
        assert TextFileReader.read_text_file(path) == UTF8_EXPECTED

    def test_read_text_file_decodes_cp1252(self, tmp_path: Path) -> None:
        """A cp1252-only byte sequence falls through utf-8 and is decoded as cp1252."""
        path: str = self.write_bytes(tmp_path, CP1252_BYTES)
        assert TextFileReader.read_text_file(path) == CP1252_EXPECTED

    def test_read_text_file_decodes_latin1(self, tmp_path: Path) -> None:
        """A latin-1-only byte sequence falls through utf-8 and cp1252, decoded as latin-1."""
        path: str = self.write_bytes(tmp_path, LATIN1_BYTES)
        assert TextFileReader.read_text_file(path) == LATIN1_EXPECTED

    def test_read_text_file_empty_file_returns_empty_string(self, tmp_path: Path) -> None:
        """An empty file decodes to an empty string."""
        path: str = self.write_bytes(tmp_path, b"")
        assert TextFileReader.read_text_file(path) == ""

    def test_read_text_file_raises_file_not_found(self, tmp_path: Path) -> None:
        """A missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            TextFileReader.read_text_file(str(tmp_path / "does_not_exist.txt"))

    # -----------------------------------------------------------------------
    # async_read_text_file
    # -----------------------------------------------------------------------

    def test_async_read_text_file_decodes_utf8(self, tmp_path: Path) -> None:
        """A UTF-8 encoded file is decoded via the utf-8 branch (async)."""
        path: str = self.write_bytes(tmp_path, UTF8_BYTES)
        assert self.run(TextFileReader.async_read_text_file(path)) == UTF8_EXPECTED

    def test_async_read_text_file_decodes_cp1252(self, tmp_path: Path) -> None:
        """A cp1252-only byte sequence falls through utf-8 and is decoded as cp1252 (async)."""
        path: str = self.write_bytes(tmp_path, CP1252_BYTES)
        assert self.run(TextFileReader.async_read_text_file(path)) == CP1252_EXPECTED

    def test_async_read_text_file_decodes_latin1(self, tmp_path: Path) -> None:
        """A latin-1-only byte sequence falls through utf-8 and cp1252, decoded as latin-1 (async)."""
        path: str = self.write_bytes(tmp_path, LATIN1_BYTES)
        assert self.run(TextFileReader.async_read_text_file(path)) == LATIN1_EXPECTED

    def test_async_read_text_file_empty_file_returns_empty_string(self, tmp_path: Path) -> None:
        """An empty file decodes to an empty string (async)."""
        path: str = self.write_bytes(tmp_path, b"")
        assert self.run(TextFileReader.async_read_text_file(path)) == ""

    def test_async_read_text_file_raises_file_not_found(self, tmp_path: Path) -> None:
        """A missing file raises FileNotFoundError (async)."""
        with pytest.raises(FileNotFoundError):
            self.run(TextFileReader.async_read_text_file(str(tmp_path / "does_not_exist.txt")))
