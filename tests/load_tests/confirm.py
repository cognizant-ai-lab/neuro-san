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

"""Strict interactive yes/no confirmation prompt.

A single reusable helper for every ``[y/n]`` prompt in the load test:
only ``y`` or ``n`` are accepted (case-insensitive), any other input
re-prompts, and Ctrl+C / EOF (closed stdin) are treated as ``n``.
"""

import logging

logger = logging.getLogger(__name__)


class Confirm:
    """Strict yes/no prompt: only y or n; Ctrl+C and EOF mean no."""

    @staticmethod
    def ask(question: str) -> bool:
        """Prompt until the user answers ``y`` or ``n``.

        Returns True for ``y`` and False for ``n``.  Ctrl+C and EOF
        (closed stdin) are treated as ``n``.  Anything else is
        rejected and the question is asked again.
        """
        prompt = f"{question} [y/n]: "
        while True:
            try:
                answer = input(prompt).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return False
            if answer == "y":
                return True
            if answer == "n":
                return False
            logger.info("  Please answer 'y' or 'n'.")
