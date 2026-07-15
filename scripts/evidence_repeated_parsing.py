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
import argparse
import logging
import os
import tempfile
from pathlib import Path

from leaf_common.serialization.format.hocon_serialization_format import HoconSerializationFormat
from neuro_san import REGISTRIES_DIR
from neuro_san.internals.graph.persistence.registry_manifest_restorer import RegistryManifestRestorer
from neuro_san.internals.persistence.abstract_async_config_restorer import AbstractAsyncConfigRestorer

logging.disable(logging.CRITICAL)  # silence the "will not be served" spam

# ---------------------------------------------------------------------------
# Instrumentation: count real parses (cache misses) and attribute them to files.
# ---------------------------------------------------------------------------

_parse_count = {"n": 0}
_orig_to_object = HoconSerializationFormat.to_object
_orig_deserialize = AbstractAsyncConfigRestorer.deserialize_file_contents


def _counting_to_object(self, fileobj):
    """Wraps HoconSerializationFormat.to_object to count every real parse."""
    # to_object is the actual pyhocon parse. A cache HIT returns from
    # deserialize_file_contents before ever reaching here, so every call
    # counted here is a genuine (re-)parse.
    _parse_count["n"] += 1
    return _orig_to_object(self, fileobj)


HoconSerializationFormat.to_object = _counting_to_object


class _Recorder:
    """Records per-file hit/miss for a single restore() call."""

    def __init__(self):
        self.calls = []  # list of (file_path, "miss"|"hit")

    def deserialize(self, restorer_self, file_path, file_contents):
        """Wraps deserialize_file_contents, tagging each file hit or miss."""
        before = _parse_count["n"]
        result = _orig_deserialize(restorer_self, file_path, file_contents)
        was_parsed = _parse_count["n"] > before
        self.calls.append((file_path, "miss" if was_parsed else "hit"))
        return result

    @property
    def misses(self):
        """Number of files that were actually (re-)parsed this restore."""
        return sum(1 for _, kind in self.calls if kind == "miss")

    @property
    def hits(self):
        """Number of files served from the cache this restore."""
        return sum(1 for _, kind in self.calls if kind == "hit")


def timed_restore(manifest_file):
    """
    Run one RegistryManifestRestorer(manifest_file).restore() with a fresh
    recorder installed, exactly the way the watcher's update_storage() does.
    :param manifest_file: path to the manifest.hocon to restore
    :return: (recorder, agent_networks)
    """
    recorder = _Recorder()

    def _patched_deserialize(restorer_self, file_path, file_contents):
        return recorder.deserialize(restorer_self, file_path, file_contents)

    AbstractAsyncConfigRestorer.deserialize_file_contents = _patched_deserialize
    try:
        networks = RegistryManifestRestorer(manifest_file).restore()
    finally:
        AbstractAsyncConfigRestorer.deserialize_file_contents = _orig_deserialize
    return recorder, networks


def served_count(networks):
    """:return: total number of served networks across all storage classes."""
    return sum(len(v) for v in networks.values())


def set_cache(enabled):
    """Enable/disable the parse cache via env var and clear any prior entries."""
    if enabled:
        os.environ["NEURO_SAN_PARSE_CACHE"] = "1"
    else:
        os.environ.pop("NEURO_SAN_PARSE_CACHE", None)
    # pylint: disable=protected-access
    AbstractAsyncConfigRestorer._deserialization_cache.clear()


# ---------------------------------------------------------------------------
# Part A: a real manifest, restored twice, cache off vs on.
# ---------------------------------------------------------------------------

def part_a(manifest_file, chdir_dir=None):
    """
    Restore a real manifest twice, cache off then on.
    :param manifest_file: path to the manifest.hocon to restore
    :param chdir_dir: optional dir to chdir into so project-root-relative
                      HOCON includes resolve (e.g. a studio checkout root)
    """
    if not Path(manifest_file).is_file():
        print(f"\n[Part A skipped] manifest not found at {manifest_file}")
        return

    prev_cwd = os.getcwd()
    if chdir_dir:
        os.chdir(chdir_dir)  # relative includes resolve against project root
    try:
        print("=" * 100)
        print("PART A: real manifest, two consecutive restores (mimics a watcher-triggered reload)")
        print("=" * 100)

        for cache_on in (False, True):
            set_cache(cache_on)
            label = "CACHE ON " if cache_on else "CACHE OFF"

            r1, nets = timed_restore(manifest_file)
            r2, _ = timed_restore(manifest_file)

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
    """Restore a controlled 3-network registry, edit one file, re-restore."""
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


def parse_args():
    """Parse --manifest / --chdir. Defaults to the neuro-san package's own manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", default=None,
        help="Path to the manifest.hocon used for Part A. Default: the neuro-san "
             "package's own neuro_san/registries/manifest.hocon (no chdir needed).")
    parser.add_argument(
        "--chdir", default=None,
        help="Directory to chdir into for Part A so project-root-relative HOCON "
             "includes resolve (e.g. a neuro-san-studio checkout root).")
    return parser.parse_args()


def resolve_manifest(manifest_arg):
    """:return: absolute manifest path - the arg if given, else the packaged default."""
    if manifest_arg:
        return os.path.abspath(manifest_arg)
    return REGISTRIES_DIR.get_file_in_basis("manifest.hocon")


def main():
    """Run Part A (real manifest) and Part B (controlled temp registry)."""
    args = parse_args()
    part_a(resolve_manifest(args.manifest), args.chdir)
    part_b()
    print("\nDone.")


if __name__ == "__main__":
    main()
