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

from os import getenv


class ExternalStorageUtil:
    """
    Utility class for common external storage policy
    """

    @staticmethod
    def get_check_interval_seconds(self) -> float:
        """
        Check if expiration interval is set by environment variable,
        and adjust it if so (overriding the constructor parameter)

        :return: The check interval in seconds from the env var.
            Can throw a Value error if the env var is invalid.
        """
        check_interval_seconds: float = None

        # Check if expiration interval is set by environment variable,
        # and adjust it if so (overriding the constructor parameter)
        envvar_name: str = "AGENT_RESERVATIONS_EXTERNAL_STORAGE_CHECK_PERIOD_SECONDS"
        envvar_value: str = getenv(envvar_name, "0")
        try:
            check_interval_seconds = float(envvar_value)
        except ValueError as exc:
            self.logger.error(
                "Invalid value for %s, must be a number. Got: %s. "
                "Please correct the environment variable or unset it.",
                envvar_name,
                envvar_value,
            )
            raise ValueError(
                f"Invalid value for {envvar_name}: expected a numeric value, got {envvar_value!r}"
            ) from exc

        return check_interval_seconds
