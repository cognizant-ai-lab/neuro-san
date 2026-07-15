#!/usr/bin/env python3
"""
Evidence that the manifest-restore path re-parses every served network from
scratch on each restore(), and that the opt-in parse cache turns a repeat
restore into (near-)zero real parses.

WHY THIS EXISTS (vs profile_manifest_restorer.py):
  The profiler proves the cache *mechanism* works when you call restore()
  twice. It does NOT prove the running server actually triggers repeat
  restores. That link is in the watcher: RegistryStorageUpdater.update_storage()
  calls RegistryManifestRestorer(...).restore() - a FULL re-restore of every
  served network - whenever ANY single .hocon/.json file under the registry
  tree changes (see registry_storage_updater.py + polling_registry_observer.py,
  recursive=True). So in a dev loop, one file save => all N networks re-parsed.

This script instruments the real parse call (HoconSerializationFormat.to_object,
which is reached only on a cache MISS - a cache hit returns before it) and
counts, per restore, how many files were actually parsed vs served from cache.

  Part A: the real studio manifest, restored twice, cache OFF then cache ON.
          Shows cache-off pays the full parse cost on BOTH restores, while
          cache-on pays it once and then parses 0 on the repeat.
  Part B: a controlled 3-network temp registry, cache ON. Restore, then change
          exactly ONE file's contents and restore again. Shows only the changed
          file re-parses (the delta), not all N - the include-aware content hash
          in action.

Run:
  python scripts/evidence_repeated_parsing.py
"""
import logging
import os
import tempfile
from pathlib import Path

logging.disable(logging.CRITICAL)  # silence the "will not be served" spam

from leaf_common.serialization.format.hocon_serialization_format import HoconSerializationFormat
from neuro_san.internals.persistence.abstract_async_config_restorer import AbstractAsyncConfigRestorer
from neuro_san.internals.graph.persistence.registry_manifest_restorer import RegistryManifestRestorer

STUDIO_MANIFEST = "/Users/2453646/neuro-san-studio/registries/manifest.hocon"
STUDIO_ROOT = "/Users/2453646/neuro-san-studio"

# ---------------------------------------------------------------------------
# Instrumentation: count real parses (cache misses) and attribute them to files.
# ---------------------------------------------------------------------------

_parse_count = {"n": 0}
_orig_to_object = HoconSerializationFormat.to_object


def _counting_to_object(self, fileobj):
    # to_object is the actual pyhocon parse. A cache HIT returns from
    # deserialize_file_contents before ever reaching here, so every call
    # counted here is a genuine (re-)parse.
    _parse_count["n"] += 1
    return _orig_to_object(self, fileobj)


HoconSerializationFormat.to_object = _counting_to_object

_orig_deserialize = AbstractAsyncConfigRestorer.deserialize_file_contents


class _Recorder:
    """Records per-file hit/miss for a single restore() call."""

    def __init__(self):
        self.calls = []  # list of (file_path, "miss"|"hit")

    def deserialize(self, restorer_self, file_path, file_contents):
        before = _parse_count["n"]
        result = _orig_deserialize(restorer_self, file_path, file_contents)
        was_parsed = _parse_count["n"] > before
        self.calls.append((file_path, "miss" if was_parsed else "hit"))
        return result

    @property
    def misses(self):
        return sum(1 for _, kind in self.calls if kind == "miss")

    @property
    def hits(self):
        return sum(1 for _, kind in self.calls if kind == "hit")


def timed_restore(manifest_file):
    """
    Run one RegistryManifestRestorer(manifest_file).restore() with a fresh
    recorder installed, exactly the way the watcher's update_storage() does.
    :return: (recorder, agent_networks)
    """
    recorder = _Recorder()
    AbstractAsyncConfigRestorer.deserialize_file_contents = \
        lambda s, fp, fc: recorder.deserialize(s, fp, fc)
    try:
        networks = RegistryManifestRestorer(manifest_file).restore()
    finally:
        AbstractAsyncConfigRestorer.deserialize_file_contents = _orig_deserialize
    return recorder, networks


def served_count(networks):
    return sum(len(v) for v in networks.values())


def set_cache(enabled):
    if enabled:
        os.environ["NEURO_SAN_PARSE_CACHE"] = "1"
    else:
        os.environ.pop("NEURO_SAN_PARSE_CACHE", None)
    AbstractAsyncConfigRestorer._deserialization_cache.clear()


# ---------------------------------------------------------------------------
# Part A: the real studio manifest, restored twice, cache off vs on.
# ---------------------------------------------------------------------------

def part_a():
    if not Path(STUDIO_MANIFEST).is_file():
        print(f"\n[Part A skipped] studio manifest not found at {STUDIO_MANIFEST}")
        return

    prev_cwd = os.getcwd()
    os.chdir(STUDIO_ROOT)  # relative includes resolve against project root
    try:
        print("=" * 100)
        print("PART A: real studio manifest, two consecutive restores (mimics a watcher-triggered reload)")
        print("=" * 100)

        for cache_on in (False, True):
            set_cache(cache_on)
            label = "CACHE ON " if cache_on else "CACHE OFF"

            r1, nets = timed_restore(STUDIO_MANIFEST)
            r2, _ = timed_restore(STUDIO_MANIFEST)

            n = served_count(nets)
            print(f"\n[{label}]  served networks: {n}")
            print(f"   1st restore: {len(r1.calls):3d} files handled -> {r1.misses:3d} parsed, {r1.hits:3d} from cache")
            print(f"   2nd restore: {len(r2.calls):3d} files handled -> {r2.misses:3d} parsed, {r2.hits:3d} from cache")
            if cache_on:
                print(f"   => repeat restore re-parsed {r2.misses} file(s) instead of {r2.hits + r2.misses}."
                      f" The cache absorbed the repeat.")
            else:
                print(f"   => repeat restore re-parsed ALL {r2.misses} file(s) again. This is the wasted work.")
    finally:
        os.chdir(prev_cwd)


# ---------------------------------------------------------------------------
# Part B: controlled 3-network registry, change ONE file, show only it reparses.
# ---------------------------------------------------------------------------

_MINIMAL_NETWORK = """{{
    "llm_config": {{ "model_name": "gpt-4o" }},
    "tools": [
        {{
            "name": "front_man_{i}",
            "function": {{ "description": "network {i} front man, revision {rev}" }},
            "instructions": "You are network {i}."
        }}
    ]
}}
"""


def part_b():
    print("\n" + "=" * 100)
    print("PART B: controlled 3-network registry, cache ON, then edit exactly ONE file and re-restore")
    print("=" * 100)

    set_cache(True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        names = [f"net{i}.hocon" for i in range(3)]
        for i, name in enumerate(names):
            (tmp_path / name).write_text(_MINIMAL_NETWORK.format(i=i, rev=0), encoding="utf-8")

        manifest = tmp_path / "manifest.hocon"
        manifest.write_text("{\n" + "\n".join(f'    "{n}": true,' for n in names) + "\n}\n", encoding="utf-8")

        r1, nets = timed_restore(str(manifest))
        print(f"\n   Initial restore: {len(r1.calls)} files handled -> {r1.misses} parsed, {r1.hits} from cache"
              f"  (served {served_count(nets)} networks)")

        # Edit exactly one served network's contents (rev 0 -> rev 1 changes bytes -> changes hash).
        edited = names[1]
        (tmp_path / edited).write_text(_MINIMAL_NETWORK.format(i=1, rev=1), encoding="utf-8")
        print(f"   Edited exactly one file: {edited}")

        r2, _ = timed_restore(str(manifest))
        reparsed = [Path(fp).name for fp, kind in r2.calls if kind == "miss"]
        print(f"   Re-restore:      {len(r2.calls)} files handled -> {r2.misses} parsed, {r2.hits} from cache")
        print(f"   => only re-parsed: {reparsed}  (the edited file's dependents, not all {len(names)})")


if __name__ == "__main__":
    part_a()
    part_b()
    print("\nDone.")
