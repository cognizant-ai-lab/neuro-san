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
