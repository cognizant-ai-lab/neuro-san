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
import tempfile
from argparse import Namespace
from unittest import TestCase

from tests.load_tests.config import DEFAULT_FIXTURES_HOCON_DIR
from tests.load_tests.validation.input_validator import InputValidator

# Real fixtures, not mocks: tests/fixtures/load_tests/hello_world/*.hocon
PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".."),
)
HELLO_WORLD_FIXTURES = os.path.join(
    PROJECT_ROOT, DEFAULT_FIXTURES_HOCON_DIR, "hello_world",
)


class TestValidateFixturesHoconDir(TestCase):
    """
    Unit tests for InputValidator.validate_fixtures_hocon_dir().

    The flag names the parent fixtures directory; the agent subfolder
    comes from --agent. A wrong path must exit clearly, not run the
    load test against the JSON prompts by mistake.
    """

    @staticmethod
    def _validator(*, agent="hello_world", fixtures_hocon_dir=None,
                   project_root=PROJECT_ROOT):
        """Build a validator with only the args this method reads."""
        return InputValidator(Namespace(
            agent=agent,
            fixtures_hocon_dir=fixtures_hocon_dir,
            project_root=project_root,
        ))

    def test_flag_absent_returns_empty_list(self):
        """No flag means prompts come from the JSON profile."""
        self.assertEqual(
            self._validator().validate_fixtures_hocon_dir(), [],
        )

    def test_default_dir_resolves_hello_world_fixtures(self):
        """DIR default + agent name -> tests/fixtures/load_tests/hello_world."""
        files = self._validator(
            fixtures_hocon_dir=DEFAULT_FIXTURES_HOCON_DIR,
        ).validate_fixtures_hocon_dir()

        expected = sorted(
            os.path.join(HELLO_WORLD_FIXTURES, name)
            for name in os.listdir(HELLO_WORLD_FIXTURES)
            if name.endswith(".hocon")
        )
        self.assertEqual(files, expected)
        self.assertEqual(len(files), 5)

    def test_prefixed_agent_uses_base_name(self):
        """basic/hello_world resolves to the hello_world subfolder."""
        files = self._validator(
            agent="basic/hello_world",
            fixtures_hocon_dir=DEFAULT_FIXTURES_HOCON_DIR,
        ).validate_fixtures_hocon_dir()
        self.assertEqual(len(files), 5)
        self.assertTrue(
            all(f.startswith(HELLO_WORLD_FIXTURES) for f in files),
        )

    def test_absolute_dir_is_used_as_is(self):
        """An absolute DIR ignores --project-root."""
        files = self._validator(
            fixtures_hocon_dir=os.path.dirname(HELLO_WORLD_FIXTURES),
            project_root="/nonexistent",
        ).validate_fixtures_hocon_dir()
        self.assertEqual(len(files), 5)

    def test_missing_agent_dir_exits(self):
        """No <DIR>/<agent>/ folder -> exit 1."""
        with self.assertRaises(SystemExit) as ctx:
            self._validator(
                agent="no_such_agent",
                fixtures_hocon_dir=DEFAULT_FIXTURES_HOCON_DIR,
            ).validate_fixtures_hocon_dir()
        self.assertEqual(ctx.exception.code, 1)

    def test_empty_agent_dir_exits(self):
        """Folder exists but holds no *.hocon -> exit 1."""
        with tempfile.TemporaryDirectory() as parent:
            os.mkdir(os.path.join(parent, "hello_world"))
            with self.assertRaises(SystemExit) as ctx:
                self._validator(
                    fixtures_hocon_dir=parent,
                ).validate_fixtures_hocon_dir()
        self.assertEqual(ctx.exception.code, 1)
