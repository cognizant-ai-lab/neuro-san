
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
hotels.example: search_hotels coded tool.

Server-side; queries a mock private inventory.
"""
from typing import Any, Dict, List

from neuro_san.interfaces.coded_tool import CodedTool


_INVENTORY: List[Dict[str, Any]] = [
    {
        "name": "Shinjuku Granbell",
        "area": "Shinjuku",
        "amenities": ["wifi", "gym", "breakfast", "non-smoking"],
        "price_usd": 215,
    },
    {
        "name": "Park Hyatt Tokyo",
        "area": "Shinjuku",
        "amenities": ["wifi", "gym", "pool", "spa", "city-view"],
        "price_usd": 720,
    },
    {
        "name": "Citadines Central Shinjuku",
        "area": "Shinjuku",
        "amenities": ["wifi", "kitchenette", "laundry"],
        "price_usd": 145,
    },
    {
        "name": "Hotel Gracery Shinjuku",
        "area": "Shinjuku",
        "amenities": ["wifi", "gym", "non-smoking"],
        "price_usd": 188,
    },
    {
        "name": "Andaz Tokyo Toranomon Hills",
        "area": "Toranomon",
        "amenities": ["wifi", "gym", "pool", "spa", "city-view"],
        "price_usd": 612,
    },
]


class SearchHotels(CodedTool):
    """Returns mock hotel candidates filtered by city / price."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        city = (args.get("city") or "").lower()
        checkin = args.get("checkin") or ""
        checkout = args.get("checkout") or ""
        max_price = args.get("max_price_usd")
        if max_price is None:
            max_price = 10000.0
        else:
            max_price = float(max_price)

        results: List[Dict[str, Any]] = []
        for hotel in _INVENTORY:
            if city and city not in hotel["area"].lower() and city not in hotel["name"].lower():
                # Allow searching for "tokyo" by matching across areas.
                if city not in {"tokyo", "shinjuku"}:
                    continue
                if city == "shinjuku" and hotel["area"].lower() != "shinjuku":
                    continue
            if hotel["price_usd"] > max_price:
                continue
            results.append({**hotel, "checkin": checkin, "checkout": checkout})
        return {"matches": results}

    def invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        raise NotImplementedError
