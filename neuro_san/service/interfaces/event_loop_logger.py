
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


class EventLoopLogger:
    """
    Interface for a logger used in event loop request processing.
    Each logger call has request-specific metadata,
    which should be presented in the logger output.
    """

    def info(self, metadata: Dict[str, Any], msg: str, *args):
        """
        "Info" logging method.
        Prepare logger filter with request-specific metadata
        and delegate logging to underlying standard Logger.
        """
        raise NotImplementedError

    def warning(self, metadata: Dict[str, Any], msg: str, *args):
        """
        "Warning" logging method.
        Prepare logger filter with request-specific metadata
        and delegate logging to underlying standard Logger.
        """
        raise NotImplementedError

    def debug(self, metadata: Dict[str, Any], msg: str, *args):
        """
        "Debug" logging method.
        Prepare logger filter with request-specific metadata
        and delegate logging to underlying standard Logger.
        """
        raise NotImplementedError

    def error(self, metadata: Dict[str, Any], msg: str, *args):
        """
        "Error" logging method.
        Prepare logger filter with request-specific metadata
        and delegate logging to underlying standard Logger.
        """
        raise NotImplementedError
