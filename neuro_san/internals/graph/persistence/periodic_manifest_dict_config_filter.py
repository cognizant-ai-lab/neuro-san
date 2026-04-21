
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
from typing import List

from logging import getLogger
from logging import Logger

from croniter import croniter as CronIter

from leaf_common.config.config_filter import ConfigFilter


class PeriodicManifestDictConfigFilter(ConfigFilter):
    """
    Implementation of the ConfigFilter interface that reads the contents
    of a single manifest configuration dictionary for an agent networks/registry,
    making sure the periodic settings are consistent with the rest of the manifest dictionary.
    """

    # Cron strings can have 5 or 6 space-delimited fields.
    # 1 is Minute (0-59)
    # 2 is Hour (0-23)
    # 3 is Day of Month (1-31)
    # 4 is Month (1-12)
    # 5 is Day of Week (0-6) where 0 is Sunday
    # 6 is Second (0-59)
    # See https://en.wikipedia.org/wiki/Cron , https://crontab.cronhub.io/ , https://github.com/pallets-eco/croniter
    ONCE_A_MINUTE: str = "*/1 * * * * 0"

    DEFAULT_CRON_SCHEDULE: str = ONCE_A_MINUTE

    def __init__(self, manifest_file: str, agent_network: str):
        """
        Constructor

        :param manifest_file: The name of the manifest file we are processing for logging purposes
        :param agent_network: The name of the agent network for logging purposes
        """
        super().__init__()
        self.manifest_file: str = manifest_file
        self.agent_network: str = agent_network

    def filter_config(self, basis_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Filters the given basis config.

        :param basis_config: The config dictionary to act as the basis
                for filtering
        :return: A config dictionary, potentially modified as per the
                policy encapsulated by the implementation
        """

        if "periodic" not in basis_config:
            basis_config["periodic"] = False
            return basis_config

        template: Dict[str, Any] = {
            # Interactions is a list of dictionaries so that we have the ability
            # to trigger multiple interactions of the same event with different data.
            # The idea here is that different specific interactions could correspond
            # to different periodicity on different state-keeping instances controlled
            # by the same event-invoked agent.
            "interactions": [
                {
                    "enable": True,
                    "cron_schedule": self.DEFAULT_CRON_SCHEDULE,
                    "second_at_beginning": False,
                    "text": "Do your thing",
                    "sly_data": {},
                    "metadata": {
                        "user_id": "system"
                    }
                }
            ]
        }

        # First pass. Maybe populate with template or single False boolean saying this doesn't apply.
        value: Any = basis_config.get("periodic")
        if isinstance(value, bool):
            if not value:
                # Just be sure we keep this whole thing off, keep the false value.
                return basis_config
        elif isinstance(value, str):
            # Take the value as the cron_schedule for periodicity
            template["interactions"][0]["cron_schedule"] = value
        elif isinstance(value, dict):
            if "interactions" not in value:
                # Take the dictionary value and merge it onto the template
                # as the first and only interaction.
                template["interactions"][0] = value
            else:
                # Take the dictionary value and shallow-merge it onto the template
                # to account for any missing values.
                template.update(value)
        # anything else gets the template as-is

        basis_config["periodic"] = template

        logger: Logger = getLogger(self.__class__.__name__)

        empty: List[Dict[str, Any]] = []
        interactions: List[Dict[str, Any]] = template.get("interactions", empty)

        # Now do late validation of cron_schedule string in each interaction
        for index, interaction in enumerate(interactions):

            cron_schedule: str = interaction.get("cron_schedule")
            if cron_schedule is None:
                interaction["cron_schedule"] = self.DEFAULT_CRON_SCHEDULE

            elif not CronIter.is_valid(cron_schedule):

                message: str = f"""
The cron_schedule "{cron_schedule}", from the {index}th interaction for network {self.agent_network}
in manifest {self.manifest_file}, does not pass strict validation.
See https://github.com/pallets-eco/croniter?tab=readme-ov-file#strict-validation as to why this might happen.
Disabling this interaction to continue.
"""
                logger.warning(message)

                # Disable the periodic dict for this interaction
                interaction["enable"] = False

        return basis_config
