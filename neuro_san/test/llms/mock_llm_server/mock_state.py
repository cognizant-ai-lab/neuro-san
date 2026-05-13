
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
See class comment for details.
"""
from __future__ import annotations

import asyncio
import json
import random

from typing import List
from typing import Optional


class MockState:
    """
    Process-wide configuration and rotating-response counter shared
    across all request handlers of the mock LLM server.
    """

    DEFAULT_RESPONSES: List[str] = [
        "Based on my analysis, the answer to your question is 42.",
        "I have reviewed the available information and here is my assessment: "
        "everything looks good and is proceeding as expected.",
        "After careful consideration, I recommend proceeding with the proposed approach. "
        "The benefits outweigh the potential risks.",
        "Here is a summary of the key findings: the data indicates positive trends "
        "across all measured dimensions.",
        "Thank you for your question. The short answer is yes, and here are the details "
        "to support that conclusion.",
        "I have completed the requested task. All items have been processed successfully "
        "and the results are ready for your review.",
        "The analysis is complete. Three main factors contribute to the observed outcome: "
        "timing, resource allocation, and coordination.",
        "Based on the information provided, I suggest the following course of action: "
        "prioritize the critical items first, then address the remaining tasks in order.",
    ]

    def __init__(
        self,
        responses: List[str],
        min_latency: float,
        max_latency: float,
        model_name: str,
        stream_token_delay: float,
    ) -> None:
        self.responses = responses
        self.min_latency = min_latency
        self.max_latency = max_latency
        self.model_name = model_name
        self.stream_token_delay = stream_token_delay
        self._counter = 0

    def next_response(self) -> str:
        """Return the next canned response, cycling through the list."""
        text = self.responses[self._counter % len(self.responses)]
        self._counter += 1
        return text

    async def sleep(self) -> None:
        """Async sleep for a random delay within [min_latency, max_latency]."""
        delay = random.uniform(self.min_latency, self.max_latency)
        await asyncio.sleep(delay)

    @classmethod
    def load_responses(cls, path: Optional[str]) -> List[str]:
        """
        Load canned responses from a JSON file (an array of strings).
        If path is None or empty, return the built-in defaults.
        """
        if not path:
            return list(cls.DEFAULT_RESPONSES)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list) or not all(isinstance(s, str) for s in data):
            raise ValueError(f"{path} must contain a JSON array of strings")
        if not data:
            raise ValueError(f"{path} must contain at least one response")
        return data
