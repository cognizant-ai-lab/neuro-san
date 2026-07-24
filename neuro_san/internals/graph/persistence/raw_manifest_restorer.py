
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

import json
from typing import Any, Dict

from pyhocon import ConfigFactory

from neuro_san.internals.persistence.abstract_async_config_restorer import AbstractAsyncConfigRestorer


class RawManifestRestorer(AbstractAsyncConfigRestorer):
    """
    Implementation of the AbstractAsyncConfigRestorer interface that reads the contents
    of a single manifest file for agent networks/registries.
    The restore() and async_restore() methods both return a dictionary.
    """

    def __init__(self):
        """
        Constructor
        """
        super().__init__(file_purpose="agent network manifest", env_var="AGENT_MANIFEST_FILE", must_exist=False)

    def deserialize_file_contents(self, file_path: str, file_contents: bytes) -> Dict[str, Any]:
        """
        Override for HOCON manifest files: use ConfigFactory.parse_file() so that
        include directives are resolved relative to the manifest file's own directory
        rather than the process CWD.

        This is backwards-compatible: parse_file() has always resolved includes
        relative to the file being parsed, so no existing include paths need to change.
        Agent HOCON files (not manifests) are unaffected — they continue to go through
        the base class which uses parse_string() and CWD-relative resolution.
        """
        if not file_path.endswith(".hocon"):
            return super().deserialize_file_contents(file_path, file_contents)

        config = ConfigFactory.parse_file(file_path)
        if config is not None:
            config = json.loads(json.dumps(config))
        return self.filter_config(config, file_path)
