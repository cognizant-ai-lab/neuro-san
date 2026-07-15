#!/usr/bin/env python3
import asyncio
import logging
import time
import statistics
from typing import List, Tuple, Dict
from leaf_common.config.file_of_class import FileOfClass
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
import os

logging.disable(logging.CRITICAL)


from neuro_san.internals.graph.persistence.registry_manifest_restorer import RegistryManifestRestorer

# Set the manifest file path
manifest_file = "/Users/2453646/neuro-san-studio/registries/manifest.hocon"
os.environ["AGENT_MANIFEST_FILE"] = manifest_file
os.environ["PYTHONPATH"]="/Users/2453646/neuro-san-studio"

# The include paths inside manifest.hocon (e.g. "registries/basic/manifest.hocon")
# and config references are relative to the project root, not the registries dir.
project_root = "/Users/2453646/neuro-san-studio"
os.chdir(project_root)

print(f"Working directory: {os.getcwd()}")
print(f"Manifest file: {manifest_file}\n")

def run():
    start_time = time.time()
    restorer = RegistryManifestRestorer()
    agent_networks: Dict[str, Dict[str, AgentNetwork]] = restorer.restore()
    manifest_files: List[str] = restorer.get_manifest_files()
    time_taken =  time.time() - start_time
    return time_taken

print(f"Without cache - Time taken: {run():.2f}s to {run():.2f}s ")

os.environ["NEURO_SAN_PARSE_CACHE"]="1"

print(f"With cache - Time taken: {run():.2f}s to {run():.2f}s ")
