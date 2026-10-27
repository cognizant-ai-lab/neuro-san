
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

import os
import unittest

from io import BytesIO
from typing import Any
from typing import Dict
from typing import List

from jsonschema import Draft202012Validator

from leaf_common.serialization.format.hocon_serialization_format import HoconSerializationFormat

from neuro_san.internals.graph.filters.network_config_filter_chain import NetworkConfigFilterChain


class TestAgentNetworkSchema(unittest.TestCase):
    """
    Guards docs/agent_network_schema.hocon against drift by validating
    every HOCON file in neuro_san/registries/ against it.
    """

    # Paths resolved against this test file so pytest's cwd does not matter
    _TEST_DIR: str = os.path.dirname(os.path.abspath(__file__))
    # tests/docs -> tests -> project_root
    _PROJECT_ROOT: str = os.path.dirname(os.path.dirname(_TEST_DIR))
    _SCHEMA_PATH: str = os.path.join(_PROJECT_ROOT, "docs", "agent_network_schema.hocon")
    _REGISTRIES_DIR: str = os.path.join(_PROJECT_ROOT, "neuro_san", "registries")

    @staticmethod
    def _load_hocon(file_path: str) -> Dict[str, Any]:
        """
        Parse a HOCON file into a dictionary with keys sanitized so
        quoted $-prefixed keys (e.g. $ref, $defs) come back unquoted.

        :param file_path: Absolute path to the HOCON file
        :return: The parsed configuration dictionary
        """
        with open(file_path, "rb") as file_obj:
            file_contents: bytes = file_obj.read()
        return HoconSerializationFormat(sanitize_keys=True).to_object(BytesIO(file_contents))

    def test_schema_file_is_valid_json_schema(self):
        """
        The schema file itself must be a syntactically valid Draft 2020-12
        JSON Schema. Catches typos and bad $refs in the schema file.
        """
        schema: Dict[str, Any] = self._load_hocon(self._SCHEMA_PATH)
        # check_schema raises SchemaError on an invalid schema
        Draft202012Validator.check_schema(schema)

    def test_every_registry_validates_against_schema(self):
        """
        Every HOCON file under neuro_san/registries/ (including nested
        folders) must validate against the shipped schema after the
        standard neuro-san filter chain has resolved commondefs
        substitutions. Any new key or shape added to a registry must
        be reflected in the schema.
        """
        schema: Dict[str, Any] = self._load_hocon(self._SCHEMA_PATH)
        validator = Draft202012Validator(schema)
        filter_chain = NetworkConfigFilterChain()

        registry_files: List[str] = self._discover_registry_files()
        self.assertGreater(len(registry_files), 0, "No registry HOCON files found")

        failures: List[str] = []
        # Validate each registry; collect every file's error so the test reports them all at once
        for registry_file in registry_files:
            file_errors: List[str] = self._validate_one_registry(registry_file, validator, filter_chain)
            if file_errors:
                basename: str = os.path.basename(registry_file)
                failures.append(f"{basename}:\n" + "\n".join(file_errors))

        if failures:
            self.fail(f"{len(failures)} registry file(s) failed schema validation:\n\n" + "\n\n".join(failures))

    def _discover_registry_files(self) -> List[str]:
        """
        Walk the whole registries tree so nested folders (e.g.
        registries/deep/) are covered. The manifest file is skipped.

        :return: Sorted list of absolute paths to every registry HOCON file
        """
        registry_files: List[str] = []
        # Walk every sub-directory under the registries root
        for dirpath, _, filenames in os.walk(self._REGISTRIES_DIR):
            for filename in filenames:
                if filename.endswith(".hocon") and filename != "manifest.hocon":
                    registry_files.append(os.path.join(dirpath, filename))
        registry_files.sort()
        return registry_files

    def _validate_one_registry(
        self,
        registry_file: str,
        validator: Draft202012Validator,
        filter_chain: NetworkConfigFilterChain,
    ) -> List[str]:
        """
        Resolve one registry's commondefs substitutions and validate it
        against the schema, returning a list of per-error messages.

        :param registry_file: Absolute path to a registry HOCON file
        :param validator: The Draft202012Validator built from the schema
        :param filter_chain: The neuro-san filter chain used for resolution
        :return: Human-readable error messages, empty when the file is valid
        """
        raw_config: Dict[str, Any] = self._load_hocon(registry_file)
        resolved_config: Dict[str, Any] = filter_chain.filter_config(raw_config)
        errors: List[str] = []
        # Collect each schema violation for this file
        for error in validator.iter_errors(resolved_config):
            path: str = "/".join(str(piece) for piece in error.absolute_path)
            errors.append(f"  at {path or '<root>'}: {error.message}")
        return errors


if __name__ == "__main__":
    unittest.main()
