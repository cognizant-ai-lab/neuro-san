
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

from typing import Any
from typing import Dict

from pathlib import Path

from leaf_common.config.file_of_class import FileOfClass
from leaf_common.persistence.easy.easy_hocon_persistence import EasyHoconPersistence
from neuro_san.internals.persistence.hocon_parse_lock import HoconParseLock


class TestsUtil:
    """
    Utility class for test cases
    """

    @staticmethod
    def parse_hocon_test_case(fixtures: FileOfClass, hocon_file: str) -> Dict[str, Any]:
        """
        Parse a hocon test case from the fixtures directory.

        :param hocon_file: The name of the hocon from the fixtures directory.
        """
        test_path: str = hocon_file
        if fixtures is not None:
            test_path = fixtures.get_file_in_basis(hocon_file)
        hocon = EasyHoconPersistence(must_exist=True)
        # pyhocon parsing mutates process-global pyparsing state and is not
        # thread-safe. See HoconParseLock. Sessions driven by this class can
        # leave background threads parsing agent hocons concurrently.
        with HoconParseLock():
            test_case: Dict[str, Any] = hocon.restore(file_reference=test_path)
            # Put the fixture name in the test case dictionary
            # to make it more self-contained for logging and reporting.
        test_case["fixture_name"] = Path(test_path).parent.name
        return test_case
