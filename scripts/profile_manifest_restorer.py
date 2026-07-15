#!/usr/bin/env python3
import cProfile
import pstats
import io
import os
import pandas as pd
from pathlib import Path
import logging
logging.disable(logging.CRITICAL)


from neuro_san.internals.graph.persistence.registry_manifest_restorer import RegistryManifestRestorer
from neuro_san.internals.persistence.abstract_async_config_restorer import AbstractAsyncConfigRestorer

# Set the manifest file path
manifest_file = "/Users/2453646/neuro-san-studio/registries/manifest.hocon"
os.environ["AGENT_MANIFEST_FILE"] = manifest_file

# The include paths inside manifest.hocon are relative to the project root
project_root = "/Users/2453646/neuro-san-studio"
os.chdir(project_root)

print(f"Working directory: {os.getcwd()}")
print(f"Manifest file: {manifest_file}\n")
print(f"NEURO_SAN_PARSE_CACHE: {os.environ.get('NEURO_SAN_PARSE_CACHE', '(unset - cache disabled)')}\n")

# Files that make up the caching + restore call chain. Everything else
# (pyparsing/pyhocon internals, dict/copy machinery, etc.) is real cost but
# isn't something our cache work can change, so it's filtered out below to
# keep the table focused on what the cache improvements actually touch.
RELEVANT_FILES = {
    "abstract_async_config_restorer.py",  # the cache itself: deserialize_file_contents,
                                           # compute_include_aware_hash, resolve_include_path
    "registry_manifest_restorer.py",      # restore_one_manifest / restore_one_agent_network
    "raw_manifest_restorer.py",           # also goes through the cached deserialize path
    "agent_network_restorer.py",          # ditto, for individual agent network files
}


def profile_one_restore():
    """
    Profiles a single, fresh RegistryManifestRestorer().restore() call.
    :return: (relevant_rows, agent_networks) where relevant_rows is a list of
             dicts (one per profiled function in RELEVANT_FILES) and
             agent_networks is the restore() result.
    """
    pr = cProfile.Profile()
    pr.enable()

    restorer = RegistryManifestRestorer()
    agent_networks = restorer.restore()

    pr.disable()

    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats('cumulative')
    ps.print_stats()

    rows = []
    for line in s.getvalue().split('\n'):
        # Skip headers and empty lines
        if not line.strip() or 'function calls' in line or 'filename:lineno' in line:
            continue

        parts = line.split()
        if len(parts) < 6:
            continue
        try:
            ncalls = parts[0]
            tottime = float(parts[1])
            percall_tot = float(parts[2])
            cumtime = float(parts[3])
            # parts[4] is per-call cumulative time - not used in the output columns below.
            func_info = ' '.join(parts[5:])

            # Extract the filename and function name separately so we can both
            # filter by file and still show the reader which file/line a
            # "restore"/"deserialize_file_contents"/etc. call came from.
            if ':' in func_info:
                filename = Path(func_info.split(':')[0]).name
                lineno_func = ':'.join(func_info.split(':')[1:])
            else:
                filename = func_info
                lineno_func = ""

            if filename not in RELEVANT_FILES:
                continue

            rows.append({
                'File': filename,
                'Function': lineno_func if lineno_func else filename,
                # 'Calls': ncalls,
                # 'Tot Time (s)': tottime,
                # 'Per Call': percall_tot,
                'Cum Time (s)': cumtime,
            })
        except (ValueError, IndexError):
            continue

    return rows, agent_networks


# First call: whatever state the process-lifetime cache is in (empty, since
# this is a fresh process - so this is always a cold/miss run).
# Second call: same manifest, same process - if the cache is enabled and
# nothing changed on disk, this is where it should pay off.
first_rows, first_networks = profile_one_restore()
second_rows, second_networks = profile_one_restore()

df_first = pd.DataFrame(first_rows)
df_second = pd.DataFrame(second_rows)

if not df_first.empty or not df_second.empty:
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
            merged[col] = merged[col].map(lambda v: f"{v:.4f}")

    print("\n" + "=" * 160)
    print(f"PROFILING RESULTS - Cache & Restore-Path Calls, 1st (cold) vs 2nd (warm) call in the same process")
    if zero_cols:
        print(f"(dropped all-zero columns: {', '.join(zero_cols)})")
    print("=" * 160)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.max_rows', None)
    pd.set_option('display.width', None)
    pd.set_option('display.max_colwidth', None)
    print(merged.to_string(index=False))
    print("=" * 160)
else:
    print("\nNo calls into the cache/restore-path modules were found in the profile.")


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


first_deserialize, first_hash = cache_breakdown(first_rows)
second_deserialize, second_hash = cache_breakdown(second_rows)
cache_enabled = AbstractAsyncConfigRestorer.is_cache_enabled()

print(f"\n🔍 CACHE-SPECIFIC BREAKDOWN:")
if cache_enabled:
    print(f"   NEURO_SAN_PARSE_CACHE is enabled - the 2nd call should hit the cache and skip re-parsing.")
    print(f"   compute_include_aware_hash = the hashing overhead the cache adds on top of a plain parse.")
    print(f"   1st call (cold): deserialize_file_contents={first_deserialize:.4f}s, compute_include_aware_hash={first_hash:.4f}s")
    print(f"   2nd call (warm): deserialize_file_contents={second_deserialize:.4f}s, compute_include_aware_hash={second_hash:.4f}s")
    if second_deserialize > 0:
        speedup = first_deserialize / second_deserialize
        hash_fraction = second_hash / second_deserialize * 100
        print(f"   -> deserialize_file_contents speedup (cold to warm): {speedup:.1f}x")
        print(f"   -> on the warm call, hashing accounts for {hash_fraction:.1f}% of that time")
        if hash_fraction < 50:
            print(f"   ⚠️  Less than half the warm call's time is hashing - the cache may not be hitting as expected.")
else:
    print(f"   NEURO_SAN_PARSE_CACHE is not set - caching is OFF, so both calls fully re-parse every file.")
    print(f"   1st call: deserialize_file_contents={first_deserialize:.4f}s")
    print(f"   2nd call: deserialize_file_contents={second_deserialize:.4f}s")
    print(f"   Any difference between these two is run-to-run variance, not caching - set NEURO_SAN_PARSE_CACHE=1 to see the cache's effect.")

# Summary statistics
print(f"\n📊 SUMMARY (2nd call):")
print(f"   Total Storage Classes: {len(second_networks)}")
for storage_class, networks in second_networks.items():
    print(f"   - {storage_class}: {len(networks)} networks")
