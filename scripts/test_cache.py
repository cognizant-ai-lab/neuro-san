#!/usr/bin/env python3
"""
Quick wall-clock check of RegistryManifestRestorer().restore() with the parse
cache off vs on. Defaults to the neuro-san package's own manifest; pass
--manifest (and --chdir for a project-root-relative manifest like studio's) to
point elsewhere. Not a rigorous benchmark - see profile_manifest_restorer.py.
"""
import argparse
import logging
import os
import time
from typing import Dict
from typing import List

from neuro_san import REGISTRIES_DIR
from neuro_san.internals.graph.persistence.registry_manifest_restorer import RegistryManifestRestorer
from neuro_san.internals.graph.registry.agent_network import AgentNetwork


def run(manifest_file: str) -> float:
    """
    Restore the manifest once.
    :param manifest_file: path to the manifest.hocon to restore
    :return: the wall-clock seconds the restore took.
    """
    start_time = time.time()
    restorer = RegistryManifestRestorer(manifest_file)
    agent_networks: Dict[str, Dict[str, AgentNetwork]] = restorer.restore()
    manifest_files: List[str] = restorer.get_manifest_files()
    # Reference the results so they are not flagged as unused.
    _ = (agent_networks, manifest_files)
    return time.time() - start_time


def parse_args():
    """Parse --manifest / --chdir. Defaults to the neuro-san package's own manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", default=None,
        help="Path to a manifest.hocon to restore. Default: the neuro-san package's "
             "own neuro_san/registries/manifest.hocon (no chdir needed).")
    parser.add_argument(
        "--chdir", default=None,
        help="Directory to change into before restoring, so HOCON includes written "
             "relative to a project root resolve (e.g. a neuro-san-studio checkout root).")
    return parser.parse_args()


def resolve_manifest(manifest_arg):
    """:return: absolute manifest path - the arg if given, else the packaged default."""
    if manifest_arg:
        return os.path.abspath(manifest_arg)
    return REGISTRIES_DIR.get_file_in_basis("manifest.hocon")


def main():
    """Set up the environment and time restore() with the cache off then on."""
    logging.disable(logging.CRITICAL)

    args = parse_args()
    if args.chdir:
        os.chdir(args.chdir)
    manifest_file = resolve_manifest(args.manifest)

    print(f"Working directory: {os.getcwd()}")
    print(f"Manifest file: {manifest_file}\n")

    print(f"Without cache - Time taken: {run(manifest_file):.2f}s to {run(manifest_file):.2f}s ")

    os.environ["NEURO_SAN_PARSE_CACHE"] = "1"

    print(f"With cache - Time taken: {run(manifest_file):.2f}s to {run(manifest_file):.2f}s ")


if __name__ == "__main__":
    main()
