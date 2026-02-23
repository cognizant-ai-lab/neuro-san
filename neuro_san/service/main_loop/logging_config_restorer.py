
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

from os import environ

from leaf_common.persistence.interface.restorer import Restorer
from leaf_common.persistence.easy.easy_hocon_persistence import EasyHoconPersistence
from leaf_common.persistence.easy.easy_json_persistence import EasyJsonPersistence

from neuro_san import DEPLOY_DIR


class LoggingConfigRestorer(Restorer):
    """
    Restorer for logging configuration.
    Allows for JSON or HOCON files as standard python logging configuration.
    """

    def __init__(self, default_file_reference: str = None):
        """
        :param default_file_reference: The file reference to use when restoring.
                Default is None, implying the file reference comes from an environment variable.
        """
        super().__init__()
        self.default_file_reference: str = environ.get("AGENT_SERVICE_LOG_JSON",
                                                       DEPLOY_DIR.get_file_in_basis("logging.json"))

    def restore(self, file_reference: str = None) -> Dict[str, Any]:
        """
        :param file_reference: The file reference to use when restoring.
                Default is None, implying the file reference is up to the
                implementation.
        :return: an object from some persisted store
        """
        use_file_reference: str = file_reference

        if file_reference is None:
            use_file_reference = self.default_file_reference

        if use_file_reference is None:
            return {}
        elif use_file_reference.endswith(".hocon"):
            return EasyHoconPersistence().restore(file_reference=use_file_reference)
        elif use_file_reference.endswith(".json"):
            return EasyJsonPersistence().restore(file_reference=use_file_reference)
        else:
            raise ValueError(f"Unsupported logging config file type: {use_file_reference}")
