
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
hotels.example: score_hotel coded tool — CLIENT SIDE.

This tool's source is shipped to the runtime as part of the distributable
network bundle.  It runs in the runtime ("browser") with no round-trip to
hotels.example.  Pure computation; no network, no I/O.
"""
from typing import Any, Dict, List

from neuro_san.interfaces.coded_tool import CodedTool


class ScoreHotel(CodedTool):
    """
    Score a single hotel against the user's stated preferences.
    Higher is better; range [0, 100].
    """

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        name: str = args.get("name") or ""
        amenities: List[str] = args.get("amenities") or []
        prefs: List[str] = args.get("user_preferences") or []
        price_usd: float = float(args.get("price_usd") or 0.0)

        amenity_set = {a.lower() for a in amenities}
        pref_set = {p.lower() for p in prefs}
        overlap = amenity_set & pref_set
        amenity_score = 60.0 * (len(overlap) / max(len(pref_set), 1))

        # Cheaper is better, but cap the price bonus so $0 doesn't dominate.
        # 40 points at $100, decaying toward 0 at $1000.
        if price_usd <= 0:
            price_score = 0.0
        else:
            price_score = max(0.0, 40.0 * (1.0 - (price_usd - 100.0) / 900.0))
            price_score = min(price_score, 40.0)

        total = round(amenity_score + price_score, 1)
        return {
            "name": name,
            "score": total,
            "matched_amenities": sorted(overlap),
            "price_usd": price_usd,
        }

    def invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        raise NotImplementedError
