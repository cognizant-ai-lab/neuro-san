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


class Formatters:
    """
    Reporting helpers for human-readable metrics and derived values.
    """

    @staticmethod
    def format_rss(rss_megabytes: float) -> str:
        """
        Format RSS in human-readable units.

        :param rss_megabytes: Resident set size in megabytes
        :return: e.g. '512M' or '1.5G'
        """
        if rss_megabytes >= 1024:
            return f"{rss_megabytes / 1024:.1f}G"
        return f"{rss_megabytes:.0f}M"

    @staticmethod
    def fmt_duration(seconds: float, precision: int = 0) -> str:
        """
        Format seconds with a minutes suffix when >= 60s.

        :param seconds: Duration in seconds
        :param precision: Decimal places for the seconds value
        :return: e.g. '1870s (31m)' or '45s' for short durations
        """
        base: str = f"{seconds:.{precision}f}s"
        if seconds >= 60:
            # Whole minutes, rounded down: 1870s is 31m.
            minutes: int = int(seconds) // 60
            return f"{base} ({minutes}m)"
        return base

    @staticmethod
    def compute_amplification(actual_requests: int, total_retries: int) -> float:
        """
        Return the retry amplification factor.

        :param actual_requests: Requests the load test sent
        :param total_retries: LLM call retries seen in the server log
        :return: 1.0 when nothing was retried; >1.0 when some LLM calls were retried
        """
        if actual_requests <= 0:
            return 1.0
        return (actual_requests + total_retries) / actual_requests
