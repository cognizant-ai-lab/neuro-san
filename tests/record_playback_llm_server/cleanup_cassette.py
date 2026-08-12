
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
Standalone tool that cleans a cassette recorded by the record/playback proxy so
it is safe for playback/hybrid: it removes any recorded FAILURE responses (a
non-2xx status such as a 429 rate limit, 401 auth error, or upstream 5xx) that
an interrupted or throttled recording session may have left behind.

Rules:
  - Single-response entry ("response"): dropped if its status is not 2xx.
  - Multi-response entry ("responses"): non-2xx variants are removed; the whole
    entry is dropped if no successful variant remains.
  - Structurally invalid entries (no usable response) are dropped.

Everything else -- request metadata, keys, latencies, unknown fields, the file's
"version" -- is preserved untouched. The tool works on the raw JSON so it is
forward-compatible with cassette fields it does not know about.

Usage:
    export PYTHONPATH=$(pwd)
    # Non-destructive: writes <cassette>.clean.json next to the input.
    python -m tests.record_playback_llm_server.cleanup_cassette session.cassette.json

    # Overwrite in place (a <cassette>.bak copy is made first).
    python -m tests.record_playback_llm_server.cleanup_cassette session.cassette.json --in-place

    # Report what would change without writing anything.
    python -m tests.record_playback_llm_server.cleanup_cassette session.cassette.json --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple


class CassetteCleaner:
    """
    Loads a cassette, strips recorded non-2xx (failure) responses, and writes a
    cleaned copy. See the module docstring for the exact rules.
    """

    @staticmethod
    def _is_success(status: Any) -> bool:
        """:return: True if the value is an HTTP 2xx status code."""
        return isinstance(status, int) and 200 <= status < 300

    @classmethod
    def clean_entries(cls, entries: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
        """
        Produce a cleaned list of entries and a stats summary.
        :param entries: The raw "entries" list from a cassette file.
        :return: (cleaned_entries, stats) where stats counts what happened.
        """
        cleaned: List[Dict[str, Any]] = []
        stats: Dict[str, int] = {
            "scanned": 0,
            "kept": 0,
            "dropped_failure": 0,
            "dropped_malformed": 0,
            "variants_removed": 0,
        }

        for entry in entries:
            stats["scanned"] += 1
            if not isinstance(entry, dict):
                stats["dropped_malformed"] += 1
                continue

            responses: Any = entry.get("responses")
            if isinstance(responses, list):
                good: List[Dict[str, Any]] = [
                    response for response in responses
                    if isinstance(response, dict) and cls._is_success(response.get("status"))
                ]
                stats["variants_removed"] += len(responses) - len(good)
                if good:
                    new_entry: Dict[str, Any] = dict(entry)
                    new_entry["responses"] = good
                    cleaned.append(new_entry)
                    stats["kept"] += 1
                else:
                    stats["dropped_failure"] += 1
                continue

            response: Any = entry.get("response")
            if isinstance(response, dict) and cls._is_success(response.get("status")):
                cleaned.append(entry)
                stats["kept"] += 1
            elif isinstance(response, dict):
                stats["dropped_failure"] += 1
            else:
                stats["dropped_malformed"] += 1

        return cleaned, stats

    @staticmethod
    def load(path: str) -> Dict[str, Any]:
        """Load and minimally validate a cassette file, exiting with a clear error on failure."""
        if not os.path.exists(path):
            raise SystemExit(f"cassette not found: {path}")
        try:
            with open(path, "r", encoding="utf-8") as cassette_file:
                data: Any = json.load(cassette_file)
        except (OSError, json.JSONDecodeError) as exception:
            raise SystemExit(f"failed to read cassette {path}: {exception}") from exception
        if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
            raise SystemExit(f"{path} is not a valid cassette (expected an object with an 'entries' list)")
        return data

    @staticmethod
    def write(path: str, data: Dict[str, Any]) -> None:
        """Write cassette data atomically (temp file + os.replace)."""
        tmp_path: str = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as cassette_file:
            json.dump(data, cassette_file, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)

    @staticmethod
    def default_output(path: str) -> str:
        """:return: The default cleaned-output path derived from the input path."""
        if path.endswith(".json"):
            return f"{path[:-5]}.clean.json"
        return f"{path}.clean.json"

    @staticmethod
    def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
        """Parse CLI arguments for the cleanup tool."""
        parser = argparse.ArgumentParser(
            description="Clean a record/playback cassette by removing non-2xx (failure) responses")
        parser.add_argument("cassette", help="Path to the cassette JSON file to clean")
        destination = parser.add_mutually_exclusive_group()
        destination.add_argument("--output", default=None,
                                 help="Where to write the cleaned cassette (default: <cassette>.clean.json)")
        destination.add_argument("--in-place", action="store_true",
                                 help="Overwrite the input cassette in place (a <cassette>.bak copy is made first)")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would be removed without writing anything")
        return parser.parse_args(argv)

    @classmethod
    def run(cls, args: argparse.Namespace) -> None:
        """Load, clean, report, and (unless dry-run) write the cleaned cassette."""
        data: Dict[str, Any] = cls.load(args.cassette)
        cleaned, stats = cls.clean_entries(data["entries"])

        logging.info(
            "scanned=%d kept=%d dropped_failure=%d dropped_malformed=%d variants_removed=%d",
            stats["scanned"], stats["kept"], stats["dropped_failure"],
            stats["dropped_malformed"], stats["variants_removed"])

        removed_entries: int = stats["dropped_failure"] + stats["dropped_malformed"]
        if removed_entries == 0 and stats["variants_removed"] == 0:
            logging.info("cassette is already clean; nothing to remove")

        if args.dry_run:
            logging.info("dry run: no file written")
            return

        data["entries"] = cleaned

        if args.in_place:
            backup_path: str = f"{args.cassette}.bak"
            shutil.copy2(args.cassette, backup_path)
            logging.info("backed up original to %s", backup_path)
            output_path: str = args.cassette
        else:
            output_path = args.output or cls.default_output(args.cassette)

        cls.write(output_path, data)
        logging.info("wrote cleaned cassette to %s (%d entries)", output_path, len(cleaned))

    @classmethod
    def main(cls, argv: Optional[List[str]] = None) -> None:
        """CLI entry point: configure logging, parse args, run."""
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        cls.run(cls.parse_args(argv))


if __name__ == "__main__":
    CassetteCleaner.main()
