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

import re
from typing import List
from typing import Optional


class RunNamer:
    """
    Builds the output folder name of a load-test run from its timestamp, host, neuro-san version and request count.
    """

    @staticmethod
    def run_folder_name(timestamp: str, host: str, neuro_san_version: Optional[str], count: int) -> str:
        """
        Build the run folder name ``<timestamp>_<host>[_ns<version>]_<count>``.

        :param timestamp: Run start time, e.g. "20261020_224538"
        :param host: The --host value
        :param neuro_san_version: neuro-san version to tag the run with, or None when unknown
        :param count: Number of requests in the run
        :return: The folder name
        """
        host_tag: str = RunNamer._host_tag(host)
        parts: List[str] = [timestamp, host_tag]
        version_tag: str = RunNamer._version_tag(neuro_san_version)
        if version_tag:
            parts.append(version_tag)
        count_text: str = str(count)
        parts.append(count_text)
        folder_name: str = "_".join(parts)
        return folder_name

    @staticmethod
    def _host_tag(host: str) -> str:
        """
        Return the --host value as a folder-name segment.

        :param host: The --host value
        :return: The host with every character other than letters, digits, ".", "+" and "-" replaced by "-"
        """
        host_text: str = str(host)
        host_tag: str = re.sub(r"[^0-9A-Za-z.+-]", "-", host_text)
        return host_tag

    @staticmethod
    def _version_tag(neuro_san_version: Optional[str]) -> str:
        """
        Return a folder-name segment for the neuro-san version.

        :param neuro_san_version: neuro-san version, or None when unknown
        :return: E.g. "ns0.6.81", or "" when the version is unknown
        """
        if not neuro_san_version:
            return ""
        safe_version: str = re.sub(r"[^0-9A-Za-z.+-]", "-", neuro_san_version)
        version_tag: str = f"ns{safe_version}"
        return version_tag
