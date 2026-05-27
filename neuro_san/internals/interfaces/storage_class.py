
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

from typing import List


class StorageClass:
    """
    Constants for AgentNetwork storage classes
    """

    PUBLIC: str = "public"          # The default - listed in Concierge
    PROTECTED: str = "protected"    # Not listed in Concierge, but still accessible by web API

    # Reserved for temporary networks that expire
    TEMP: str = "temp"              # Not listed in Concierge, accessible by web API

    # Note: "temp" not listed here because it is so unlike everything else.
    ALL_PERMANENT: List[str] = [PUBLIC, PROTECTED]
