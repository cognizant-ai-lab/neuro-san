#!/usr/bin/env python3
"""
cProfile-based profiler for RegistryManifestRestorer().restore(), focused on
the cache + restore call chain. Profiles two consecutive restores in the same
process (1st = cold, 2nd = warm) and prints, per relevant function, the
cumulative time for each - so you can see the parse cache pay off on the 2nd
call when NEURO_SAN_PARSE_CACHE is enabled.
"""
import argparse
import cProfile
import io
import logging
import os
import pstats
from pathlib import Path

import pandas as pd

from neuro_san import REGISTRIES_DIR
from neuro_san.internals.graph.persistence.registry_manifest_restorer import RegistryManifestRestorer
from neuro_san.internals.persistence.abstract_async_config_restorer import AbstractAsyncConfigRestorer

# Files that make up the caching + restore call chain. Everything else
# (pyparsing/pyhocon internals, dict/copy machinery, etc.) is real cost but
# isn't something our cache work can change, so it's filtered out below to
# keep the table focused on what the cache improvements actually touch.
RELEVANT_FILES = {
    # the cache itself: deserialize_file_contents, compute_include_aware_hash, resolve_include_path
    "abstract_async_config_restorer.py",
    # restore_one_manifest / restore_one_agent_network
    "registry_manifest_restorer.py",
    # also goes through the cached deserialize path
    "raw_manifest_restorer.py",
    # ditto, for individual agent network files
    "agent_network_restorer.py",
}


def profile_one_restore(manifest_file):
    """
    Profiles a single, fresh RegistryManifestRestorer(manifest_file).restore() call.
    :param manifest_file: path to the manifest.hocon to restore
    :return: (relevant_rows, agent_networks) where relevant_rows is a list of
             dicts (one per profiled function in RELEVANT_FILES) and
             agent_networks is the restore() result.
    """
    profiler = cProfile.Profile()
    profiler.enable()

    restorer = RegistryManifestRestorer(manifest_file)
    agent_networks = restorer.restore()

    profiler.disable()

    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream).sort_stats('cumulative')
    stats.print_stats()

    rows = []
    for line in stream.getvalue().split('\n'):
        # Skip headers and empty lines
        if not line.strip() or 'function calls' in line or 'filename:lineno' in line:
            continue

        parts = line.split()
        if len(parts) < 6:
            continue
        try:
            # parts[0..2] are ncalls/tottime/percall - not shown; parts[4] is
            # per-call cumulative time. We only report cumulative time (parts[3]).
            cumtime = float(parts[3])
            func_info = ' '.join(parts[5:])

            # Extract the filename and function name separately so we can both
            # filter by file and still show the reader which file/line a
            # "restore"/"deserialize_file_contents"/etc. call came from.
            if ':' in func_info:
                filename = Path(func_info.split(':', maxsplit=1)[0]).name
                lineno_func = ':'.join(func_info.split(':')[1:])
            else:
                filename = func_info
                lineno_func = ""

            if filename not in RELEVANT_FILES:
                continue

            rows.append({
                'File': filename,
                'Function': lineno_func if lineno_func else filename,
                'Cum Time (s)': cumtime,
            })
        except (ValueError, IndexError):
            continue

    return rows, agent_networks


def print_comparison_table(first_rows, second_rows):
    """Print the 1st-call vs 2nd-call cumulative-time comparison table."""
    df_first = pd.DataFrame(first_rows)
    df_second = pd.DataFrame(second_rows)

    if df_first.empty and df_second.empty:
        print("\nNo calls into the cache/restore-path modules were found in the profile.")
        return

    merged = pd.merge(
        df_first, df_second,
        on=['File', 'Function'],
        how='outer',
        suffixes=(' (1st call)', ' (2nd call)'),
    ).fillna(0)

    # Sort by whichever call had the larger cumulative cost for that function.
    merged['_sort_key'] = merged[['Cum Time (s) (1st call)', 'Cum Time (s) (2nd call)']].max(axis=1)
    merged = merged.sort_values('_sort_key', ascending=False).drop(columns=['_sort_key'])

    # Drop columns that are all zero for both calls - no signal to show.
    numeric_cols = [c for c in merged.columns if c not in ('File', 'Function')]
    zero_cols = [c for c in numeric_cols if (merged[c] == 0).all()]
    merged = merged.drop(columns=zero_cols)

    # Round remaining float columns for display.
    for col in merged.columns:
        if merged[col].dtype.kind == 'f':
            merged[col] = merged[col].map(lambda value: f"{value:.4f}")

    print("\n" + "=" * 160)
    print("PROFILING RESULTS - Cache & Restore-Path Calls, 1st (cold) vs 2nd (warm) call in the same process")
    if zero_cols:
        print(f"(dropped all-zero columns: {', '.join(zero_cols)})")
    print("=" * 160)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.max_rows', None)
    pd.set_option('display.width', None)
    pd.set_option('display.max_colwidth', None)
    print(merged.to_string(index=False))
    print("=" * 160)


def cache_breakdown(rows):
    """
    :param rows: relevant_rows from one profile_one_restore() call
    :return: (deserialize_time, hash_time) cumulative seconds
    """
    hash_time = sum(r['Cum Time (s)'] for r in rows
                    if r['File'] == 'abstract_async_config_restorer.py'
                    and 'compute_include_aware_hash' in r['Function'])
    deserialize_time = sum(r['Cum Time (s)'] for r in rows
                           if r['File'] == 'abstract_async_config_restorer.py'
                           and 'deserialize_file_contents' in r['Function'])
    return deserialize_time, hash_time


def print_cache_breakdown(first_rows, second_rows):
    """Print the cache-specific breakdown, worded for cache-on vs cache-off."""
    first_deserialize, first_hash = cache_breakdown(first_rows)
    second_deserialize, second_hash = cache_breakdown(second_rows)

    print("\n🔍 CACHE-SPECIFIC BREAKDOWN:")
    if not AbstractAsyncConfigRestorer.is_cache_enabled():
        print("   NEURO_SAN_PARSE_CACHE is not set - caching is OFF, so both calls fully re-parse every file.")
        print(f"   1st call: deserialize_file_contents={first_deserialize:.4f}s")
        print(f"   2nd call: deserialize_file_contents={second_deserialize:.4f}s")
        print("   Any difference between these two is run-to-run variance, not caching -"
              " set NEURO_SAN_PARSE_CACHE=1 to see the cache's effect.")
        return

    print("   NEURO_SAN_PARSE_CACHE is enabled - the 2nd call should hit the cache and skip re-parsing.")
    print("   compute_include_aware_hash = the hashing overhead the cache adds on top of a plain parse.")
    print(f"   1st call (cold): deserialize_file_contents={first_deserialize:.4f}s,"
          f" compute_include_aware_hash={first_hash:.4f}s")
    print(f"   2nd call (warm): deserialize_file_contents={second_deserialize:.4f}s,"
          f" compute_include_aware_hash={second_hash:.4f}s")
    if second_deserialize > 0:
        speedup = first_deserialize / second_deserialize
        print(f"   -> deserialize_file_contents speedup (cold to warm): {speedup:.1f}x")
        # Speedup is the reliable "is the cache hitting" signal. (Hash-fraction is
        # not: on a small/fast manifest the warm times are sub-millisecond, where
        # the hash-vs-total ratio is just timing noise.)
        if speedup < 2:
            print("   ⚠️  Warm call was not meaningfully faster than cold -"
                  " the cache may not be hitting as expected.")


def parse_args():
    """Parse --manifest / --chdir. Defaults to the neuro-san package's own manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", default=None,
        help="Path to a manifest.hocon to restore. Default: the neuro-san package's "
             "own neuro_san/registries/manifest.hocon (33 networks, no chdir needed).")
    parser.add_argument(
        "--chdir", default=None,
        help="Directory to change into before restoring, so HOCON includes written "
             "relative to a project root resolve (e.g. a neuro-san-studio checkout root). "
             "Not needed for the neuro-san package manifest.")
    return parser.parse_args()


def resolve_manifest(manifest_arg):
    """:return: absolute manifest path - the arg if given, else the packaged default."""
    if manifest_arg:
        return os.path.abspath(manifest_arg)
    return REGISTRIES_DIR.get_file_in_basis("manifest.hocon")


def main():
    """Set up the environment, profile two restores, and print the results."""
    logging.disable(logging.CRITICAL)

    args = parse_args()
    if args.chdir:
        os.chdir(args.chdir)
    manifest_file = resolve_manifest(args.manifest)

    print(f"Working directory: {os.getcwd()}")
    print(f"Manifest file: {manifest_file}\n")
    print(f"NEURO_SAN_PARSE_CACHE: {os.environ.get('NEURO_SAN_PARSE_CACHE', '(unset - cache disabled)')}\n")

    # First call: fresh process, so the cache (if enabled) is empty -> cold.
    # Second call: same manifest, same process -> warm if the cache is enabled.
    first_rows, _ = profile_one_restore(manifest_file)
    second_rows, second_networks = profile_one_restore(manifest_file)

    print_comparison_table(first_rows, second_rows)
    print_cache_breakdown(first_rows, second_rows)

    print("\n📊 SUMMARY (2nd call):")
    print(f"   Total Storage Classes: {len(second_networks)}")
    for storage_class, networks in second_networks.items():
        print(f"   - {storage_class}: {len(networks)} networks")


if __name__ == "__main__":
    main()
