
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
flights.example: search_flights coded tool.

This is a server-side tool — the inventory below is the agent's private data
and never leaves the origin.  Clients hit this tool via the Agent Web
POST /api/v1/flight_finder/tool/search_flights endpoint.
"""
from typing import Any, Dict, List

from neuro_san.interfaces.coded_tool import CodedTool


# Mock private inventory; in a real deployment this would be a DB query.
_INVENTORY: List[Dict[str, Any]] = [
    {"flight_id": "AA-7311", "origin": "SFO", "destination": "NRT",
     "carrier": "American", "depart": "07:55", "arrive": "11:40+1",
     "stops": 0, "duration_h": 11.7, "price_usd": 1284},
    {"flight_id": "UA-0837", "origin": "SFO", "destination": "NRT",
     "carrier": "United", "depart": "10:50", "arrive": "14:20+1",
     "stops": 0, "duration_h": 11.5, "price_usd": 1199},
    {"flight_id": "ZP-2261", "origin": "SFO", "destination": "NRT",
     "carrier": "ZipAir", "depart": "21:10", "arrive": "01:30+2",
     "stops": 1, "duration_h": 14.3, "price_usd": 742},
    {"flight_id": "JL-0001", "origin": "SFO", "destination": "HND",
     "carrier": "JAL", "depart": "13:15", "arrive": "17:05+1",
     "stops": 0, "duration_h": 11.0, "price_usd": 1620},
]


class SearchFlights(CodedTool):
    """CodedTool that returns matching mock flights."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        origin = (args.get("origin") or "").upper()
        destination = (args.get("destination") or "").upper()
        date = args.get("date") or ""

        results: List[Dict[str, Any]] = []
        for flight in _INVENTORY:
            if origin and flight["origin"] != origin:
                continue
            if destination and flight["destination"] not in (destination, "HND" if destination == "TYO" else destination):
                # Treat TYO as either NRT or HND (the two Tokyo airports).
                if not (destination == "TYO" and flight["destination"] in ("NRT", "HND")):
                    continue
            results.append({**flight, "date": date})
        if not results:
            return {
                "matches": [],
                "note": f"No flights matched {origin}->{destination} on {date}",
            }
        return {"matches": results, "date": date}

    def invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        raise NotImplementedError
