
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
"""
Shared test builders for LocalReservationsStorage unit tests.

The class defined here is imported by sibling test_local_reservations_storage_*.py
modules. Grouping the helpers into a single class (rather than module-level
functions) matches the project's coding policy of one class per file with
no stand-alone functions.
"""
import time
from typing import Any
from typing import Dict
from typing import Optional

from neuro_san.internals.reservations.agent_reservation import AgentReservation


class LocalReservationsTestHelpers:
    """
    Static-method container for constructing reservations and agent specs
    used by the LocalReservationsStorage test suite.
    """

    @staticmethod
    def make_reservation(prefix: str, lifetime_s: float,
                         expires_offset_s: Optional[float] = None) -> AgentReservation:
        """
        Build an AgentReservation with a deterministic expiration.

        :param prefix: The prefix used to build the reservation id.
        :param lifetime_s: Lifetime handed to the AgentReservation constructor.
        :param expires_offset_s: Offset (in seconds) from now that the
                                 reservation should expire. Positive = future,
                                 negative = past. When None, defaults to
                                 `lifetime_s` (i.e. expires in `lifetime_s`
                                 seconds from now).
        :return: A configured AgentReservation ready for storage.
        """
        reservation: AgentReservation = AgentReservation(
            lifetime_in_seconds=lifetime_s, prefix=prefix)
        offset: float = lifetime_s if expires_offset_s is None else expires_offset_s
        now: float = time.time()
        # set_expiration_from() clamps to min(lifetime, max_lifetime), so pass
        # a big max_lifetime and let use_now_in_seconds set the deadline where
        # we want it.
        reservation.set_expiration_from(
            use_now_in_seconds=now + offset - lifetime_s,
            max_lifetime_in_seconds=lifetime_s + 1.0,
        )
        return reservation

    @staticmethod
    def make_spec() -> Dict[str, Any]:
        """
        Return a minimal deployable agent-spec dictionary suitable for
        being written by LocalReservationsStorage.add_reservations().

        :return: A fresh dict; safe to pass into add_reservations() without
                 worrying about accidental mutation across tests.
        """
        return {"name": "n", "llm_config": {"model": "gpt"}, "tools": []}
