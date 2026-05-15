
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
flights.example: book_hold coded tool.

Server-side; uses the passenger_email from sly_data to issue a fake booking
hold code.  In a real deployment this would call the airline's hold API and
charge a small refundable deposit.
"""
import secrets
import string
from typing import Any, Dict

from neuro_san.interfaces.coded_tool import CodedTool


def _generate_code(length: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class BookHold(CodedTool):
    """Issues a fake refundable booking hold."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        flight_id: str = args.get("flight_id") or ""
        passenger_email: str = (sly_data or {}).get("passenger_email") or ""

        if not flight_id:
            return {"error": "flight_id is required"}
        if not passenger_email or "@" not in passenger_email:
            return {
                "error": (
                    "passenger_email is required in sly_data to place a hold.  "
                    "Ask the user for their email and route it through sly_data."
                )
            }

        code = f"HOLD-{_generate_code()}"
        # Surface the booking code back as sly_data; the agent's
        # allow.from_downstream rule will let it through.
        if isinstance(sly_data, dict):
            sly_data["last_booking_code"] = code
        return {
            "booking_code": code,
            "flight_id": flight_id,
            "passenger_email": passenger_email,
            "hold_minutes": 15,
            "note": "Refundable hold placed. Confirm within 15 minutes to lock in.",
        }

    def invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        raise NotImplementedError
