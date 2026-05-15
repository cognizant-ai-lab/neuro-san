
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
travelgenius.example: total_cost coded tool — CLIENT SIDE.

Pure computation; runs in the runtime's sandbox.
"""
from typing import Any, Dict

from neuro_san.interfaces.coded_tool import CodedTool


class TotalCost(CodedTool):
    """Sums flight cost and hotel nightly cost * nights."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        flight = float(args.get("flight_cost_usd") or 0.0)
        hotel_nightly = float(args.get("hotel_nightly_usd") or 0.0)
        nights = int(args.get("nights") or 0)
        hotel_total = round(hotel_nightly * nights, 2)
        total = round(flight + hotel_total, 2)
        return {
            "flight_cost_usd": round(flight, 2),
            "hotel_cost_usd": hotel_total,
            "nights": nights,
            "total_usd": total,
        }

    def invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        raise NotImplementedError
