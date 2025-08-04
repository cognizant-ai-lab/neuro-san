from typing import Any
from typing import Dict
from typing import Union

from logging import getLogger
from logging import Logger

from neuro_san.interfaces.coded_tool import CodedTool


class Accountant(CodedTool):
    """
    A tool that updates a running cost each time it is called.
    """

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Union[Dict[str, Any], str]:
        """
        Updates the passed running cost each time it's called.
        :param args: A dictionary with the following keys:
                    "running_cost": the running cost to update.

        :param sly_data: A dictionary containing parameters that should be kept out of the chat stream.
                         Keys expected for this implementation are:
                         None

        :return: A dictionary containing:
                 "running_cost": the updated running cost.
        """
        tool_name = self.__class__.__name__
        logger: Logger = getLogger(self.__class__.__name__)

        logger.debug(f"========== Calling {tool_name} ==========")
        # Parse the arguments
        logger.debug(f"args: {args}")
        running_cost: float = float(args.get("running_cost"))

        # Increment the running cost not using value other 1
        # This would make a little hard if the LLM wanted to guess
        updated_running_cost: float = running_cost + 3.0

        tool_response = {
            "running_cost": updated_running_cost
        }
        logger.debug("-----------------------")
        logger.debug(f"{tool_name} response: ", tool_response)
        logger.debug(f"========== Done with {tool_name} ==========")
        return tool_response
