
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
from __future__ import annotations

import json
import os

from typing import Any
from typing import Dict
from typing import List
from typing import Optional


class Cassette:
    """
    On-disk store of recorded request -> response interactions.

    Entries are keyed by the sha256 request signature produced by
    RequestCanonicalizer. In memory they live in a dict for O(1) lookup; on
    disk they are written as an ordered JSON array so the file stays
    human-diffable and reviewable in git -- which is where the test
    repeatability actually comes from: the recorded run becomes a committed
    fixture.

    Each entry is a dict of the shape:
        {
            "key": "<sha256>",
            "method": "POST",
            "path": "/chat/completions",
            "request": "<canonical request string>",
            "response": { ... see record modes below ... }
        }

    A non-streamed response is stored as:
        {"kind": "json", "status": 200, "body": <parsed JSON or raw string>}

    A streamed response is stored as:
        {"kind": "stream", "status": 200, "chunks": ["data: {...}\\n\\n", ...]}
    """

    VERSION: int = 1

    def __init__(self, path: str) -> None:
        """
        :param path: Filesystem path of the cassette JSON file. Loaded now if
                     it exists; created on the first save otherwise.
        """
        self.path: str = path
        self.entries: Dict[str, Dict[str, Any]] = {}
        self._order: List[str] = []
        self.load()

    def load(self) -> None:
        """Load entries from disk into memory. A missing file is not an error."""
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as cassette_file:
                data: Dict[str, Any] = json.load(cassette_file)
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"Failed to load cassette '{self.path}': {exc}") from exc
        for entry in data.get("entries", []):
            key: Optional[str] = entry.get("key")
            if key is None:
                continue
            if key not in self.entries:
                self._order.append(key)
            self.entries[key] = entry

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """:return: The recorded entry for the key, or None if not present."""
        return self.entries.get(key)

    def put(self, key: str, entry: Dict[str, Any]) -> None:
        """
        Insert or overwrite the entry for a key and persist the whole cassette.
        :param key: The request signature key.
        :param entry: The entry dict; its "key" field is set from `key`.
        """
        entry["key"] = key
        if key not in self.entries:
            self._order.append(key)
        self.entries[key] = entry
        self.save()

    def append_response(self, key: str, meta: Dict[str, Any], response: Dict[str, Any]) -> None:
        """
        Multi-response record: append a distinct response for a key, keeping all
        variants under a "responses" list for round-robin playback. Responses
        whose content matches an existing one (ignoring timing fields) are not
        duplicated. Persists the whole cassette.
        :param key: The request signature key.
        :param meta: Request metadata (method, path, request) for a new entry.
        :param response: The response dict to append.
        """
        entry: Optional[Dict[str, Any]] = self.entries.get(key)
        if entry is None:
            entry = dict(meta)
            entry["key"] = key
            entry["responses"] = [response]
            self.entries[key] = entry
            self._order.append(key)
        else:
            responses: List[Dict[str, Any]] = entry.setdefault("responses", [])
            if not any(self._same_content(existing, response) for existing in responses):
                responses.append(response)
        self.save()

    @staticmethod
    def _same_content(first: Dict[str, Any], second: Dict[str, Any]) -> bool:
        """Compare two responses for equality ignoring per-call timing fields."""
        return Cassette._content_key(first) == Cassette._content_key(second)

    @staticmethod
    def _content_key(response: Dict[str, Any]) -> str:
        """Serialize a response for de-duplication, stripping volatile timing fields."""
        trimmed: Dict[str, Any] = dict(response)
        trimmed.pop("latency_seconds", None)
        trimmed.pop("first_byte_seconds", None)
        return json.dumps(trimmed, sort_keys=True)

    def save(self) -> None:
        """
        Write the cassette to disk atomically (temp file + os.replace) so a
        crash mid-write cannot corrupt an existing cassette.
        """
        data: Dict[str, Any] = {
            "version": self.VERSION,
            "entries": [self.entries[key] for key in self._order],
        }
        tmp_path: str = f"{self.path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as cassette_file:
            json.dump(data, cassette_file, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self.path)

    def __len__(self) -> int:
        """:return: Number of recorded entries."""
        return len(self.entries)
