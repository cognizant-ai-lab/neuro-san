
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

from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from unittest import TestCase
from unittest.mock import patch

import neuro_san

from neuro_san.internals.graph.registry.activation_factory import ActivationFactory
from neuro_san.internals.graph.registry.agent_network import AgentNetwork


class TestActivationFactory(TestCase):
    """
    Unit tests for how ActivationFactory reads AGENT_TOOL_PATH: each root it lists
    becomes one dotted module path, ending with the agent network name, under which
    coded tools are looked up.
    """

    # The repo root is the PYTHONPATH entry that directory roots are mapped against.
    REPO_ROOT: str = str(Path(__file__).resolve().parents[5])
    # A tool root laid out like a project's coded_tools directory, used as a directory root
    FIRST_AGENT_TOOL_PATH_DIR: str = str(Path(REPO_ROOT, "tests", "first_agent_tool_path"))
    FIRST_AGENT_TOOL_PATH_PACKAGE: str = "tests.first_agent_tool_path"
    # A second tool root of the same shape, used as a module-path root
    SECOND_AGENT_TOOL_PATH_PACKAGE: str = "tests.second_agent_tool_path"
    # A PYTHONPATH entry that holds no tool root and is not an ancestor of the working directory,
    # so a root that is wrongly mapped as a directory cannot be mapped by accident.
    OTHER_PYTHONPATH: str = str(Path(REPO_ROOT, "docs"))
    # Where the imported neuro_san package lives, for the default root
    PACKAGE_PARENT: str = str(Path(neuro_san.__file__).resolve().parent.parent)
    NETWORK_NAME: str = "my_network"

    def make_factory(self, network_name: str, agent_tool_path: Optional[str],
                     pythonpath: str = None) -> ActivationFactory:
        """
        Builds a factory around a minimal AgentNetwork with a single front man, with
        AGENT_TOOL_PATH and PYTHONPATH pinned while the factory reads them.

        :param network_name: The name of the agent network, as the manifest registers it
        :param agent_tool_path: The AGENT_TOOL_PATH value, or None to leave the variable unset
        :param pythonpath: The PYTHONPATH value. None means OTHER_PYTHONPATH, which maps no root.
        :return: An ActivationFactory whose tool paths come from those values
        :raises ValueError: If the factory rejects the AGENT_TOOL_PATH value
        """
        config: Dict[str, Any] = {
            "tools": [
                {
                    "name": "front",
                    "function": {"description": "x"},
                },
            ],
        }
        agent_network: AgentNetwork = AgentNetwork(config, network_name)

        use_pythonpath: str = pythonpath
        if use_pythonpath is None:
            use_pythonpath = TestActivationFactory.OTHER_PYTHONPATH

        with patch.dict(os.environ, {"PYTHONPATH": use_pythonpath}):
            if agent_tool_path is None:
                os.environ.pop("AGENT_TOOL_PATH", None)
            else:
                os.environ["AGENT_TOOL_PATH"] = agent_tool_path
            return ActivationFactory(agent_network)

    def test_module_path_root_is_used_as_is(self) -> None:
        """
        A root without a path separator is a Python module path. It is used as given,
        with the agent network name added, so it can name tools installed as a package.
        """
        factory: ActivationFactory = self.make_factory(TestActivationFactory.NETWORK_NAME, "neuro_san.coded_tools")

        self.assertEqual(factory.get_agent_tool_paths(), ["neuro_san.coded_tools.my_network"])

    def test_directory_root_is_mapped_through_pythonpath(self) -> None:
        """
        A directory root becomes the module path beneath the PYTHONPATH entry that holds it.
        """
        factory: ActivationFactory = self.make_factory(
            TestActivationFactory.NETWORK_NAME, TestActivationFactory.FIRST_AGENT_TOOL_PATH_DIR,
            TestActivationFactory.REPO_ROOT)

        expected: List[str] = [f"{TestActivationFactory.FIRST_AGENT_TOOL_PATH_PACKAGE}.my_network"]
        self.assertEqual(factory.get_agent_tool_paths(), expected)

    def test_several_roots_keep_their_order(self) -> None:
        """
        A list of roots, directories and module paths mixed, gives one tool path per root
        in the order listed.
        """
        roots: List[str] = [
            TestActivationFactory.FIRST_AGENT_TOOL_PATH_DIR,
            TestActivationFactory.SECOND_AGENT_TOOL_PATH_PACKAGE,
        ]
        factory: ActivationFactory = self.make_factory(
            TestActivationFactory.NETWORK_NAME, os.pathsep.join(roots), TestActivationFactory.REPO_ROOT)

        expected: List[str] = [
            f"{TestActivationFactory.FIRST_AGENT_TOOL_PATH_PACKAGE}.my_network",
            f"{TestActivationFactory.SECOND_AGENT_TOOL_PATH_PACKAGE}.my_network",
        ]
        self.assertEqual(factory.get_agent_tool_paths(), expected)

    def test_blank_entries_are_dropped(self) -> None:
        """
        Blank entries, such as one left by a trailing separator, are not roots, and
        whitespace around an entry is ignored.
        """
        value: str = f" first.root {os.pathsep}{os.pathsep} second.root {os.pathsep}"
        factory: ActivationFactory = self.make_factory(TestActivationFactory.NETWORK_NAME, value)

        self.assertEqual(factory.get_agent_tool_paths(), ["first.root.my_network", "second.root.my_network"])

    def test_only_blank_entries_raise(self) -> None:
        """
        A value with no usable root is an error, not a silent fallback.
        """
        with self.assertRaises(ValueError) as raised_error:
            self.make_factory(TestActivationFactory.NETWORK_NAME, f" {os.pathsep} ")

        self.assertIn("AGENT_TOOL_PATH", str(raised_error.exception))

    def test_directory_root_outside_pythonpath_raises(self) -> None:
        """
        A directory root that no PYTHONPATH entry holds is an error that names the root,
        even when another root in the list is fine.
        """
        unmapped_root: str = TestActivationFactory.FIRST_AGENT_TOOL_PATH_DIR
        roots: List[str] = [unmapped_root, "neuro_san.coded_tools"]
        with self.assertRaises(ValueError) as raised_error:
            self.make_factory(TestActivationFactory.NETWORK_NAME, os.pathsep.join(roots))

        expected: str = f"No reasonable agent tool path found in PYTHONPATH for {unmapped_root}"
        self.assertIn(expected, str(raised_error.exception))

    def test_hierarchical_network_name_becomes_dotted_suffix(self) -> None:
        """
        The slashes of a hierarchical agent network name become dots in the tool path.
        """
        factory: ActivationFactory = self.make_factory("deep/math_guy", "neuro_san.coded_tools")

        self.assertEqual(factory.get_agent_tool_paths(), ["neuro_san.coded_tools.deep.math_guy"])

    def test_root_already_ending_with_network_name_is_not_suffixed_again(self) -> None:
        """
        A root that already ends with the agent network name is used as is.
        """
        factory: ActivationFactory = self.make_factory("math_guy", "neuro_san.coded_tools.math_guy")

        self.assertEqual(factory.get_agent_tool_paths(), ["neuro_san.coded_tools.math_guy"])

    def test_unset_variable_falls_back_to_shipped_coded_tools(self) -> None:
        """
        With no AGENT_TOOL_PATH, the single root is the coded_tools directory shipped with neuro-san.
        """
        factory: ActivationFactory = self.make_factory(
            TestActivationFactory.NETWORK_NAME, None, TestActivationFactory.PACKAGE_PARENT)

        self.assertEqual(factory.get_agent_tool_paths(), ["neuro_san.coded_tools.my_network"])
