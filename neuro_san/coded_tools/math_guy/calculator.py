
# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT

from typing import Any
from typing import Dict

from neuro_san.interfaces.coded_tool import CodedTool
from neuro_san.coded_tools.math_guy.async_closeable import AsyncCloseable
from neuro_san.coded_tools.math_guy.sync_closeable import SyncCloseable


class Calculator(CodedTool):
    """
    CodedTool implementation of a calculator for the math_guy test.

    Upon activation by the agent hierarchy, a CodedTool will have its
    invoke() call called by the system.

    Implementations are expected to clean up after themselves.
    """

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        """
        Called when the coded tool is invoked asynchronously by the agent hierarchy.
        Strongly consider overriding this method instead of the "easier" synchronous
        version above when the possibility of making any kind of call that could block
        (like sleep() or a socket read/write out to a web service) is within the
        scope of your CodedTool.

        :param args: An argument dictionary whose keys are the parameters
                to the coded tool and whose values are the values passed for them
                by the calling agent.  This dictionary is to be treated as read-only.
        :param sly_data: A dictionary whose keys are defined by the agent hierarchy,
                but whose values are meant to be kept out of the chat stream.

                This dictionary is largely to be treated as read-only.
                It is possible to add key/value pairs to this dict that do not
                yet exist as a bulletin board, as long as the responsibility
                for which coded_tool publishes new entries is well understood
                by the agent chain implementation and the coded_tool implementation
                adding the data is not invoke()-ed more than once.
        :return: A return value that goes into the chat stream.
        """
        retval: float = 0.0

        operator: str = args.get("operator")
        if operator is None or not isinstance(operator, str):
            return "Don't understand non-string operators"

        x: float = sly_data.get("x")
        y: float = sly_data.get("y")

        if x is None or y is None:
            return "Need to set keys x and y in the sly_data as float operands"

        x = float(x)
        y = float(y)

        operator = operator.lower()
        if operator in ("add", "addition", "+", "plus"):
            retval = x + y
        elif operator in ("subtract", "subtraction", "-", "minus"):
            retval = x - y
        elif operator in ("multiply", "multiplication", "*", "times"):
            retval = x * y
        elif operator in ("divide", "division", "/", "over", "divided by"):
            if y != 0:
                retval = x / y
            else:
                return "Can't divide by 0"

        sly_data["equals"] = retval

        # Add close()-able objects to test closing of sly_data
        # These are only to enhance testing coverage and are non-essential
        # to the function of this coded tool.
        sly_data["sync_closeable"] = SyncCloseable()
        sly_data["async_closeable"] = AsyncCloseable()

        return "Check sly_data['equals'] for the result"
