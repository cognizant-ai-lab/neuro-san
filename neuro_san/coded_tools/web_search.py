
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
from typing import Union

import logging

from ddgs import DDGS

from neuro_san.interfaces.coded_tool import CodedTool


class WebSearch(CodedTool):
    """
    CodedTool implementation which provides a way to utilize different websites' search feature
    """

    def __init__(self):
        self.top_n = 5

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Union[Dict[str, Any], str]:
        """
        As much as we'd prefer an asynchronous entry point, the code below uses synchronous
        calls for a simple example. Asynchronous calls make for a more performant server
        environment.
        """
        raise NotImplementedError

    def invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Union[Dict[str, Any], str]:
        """
        :param args: An argument dictionary whose keys are the parameters
                to the coded tool and whose values are the values passed for them
                by the calling agent.  This dictionary is to be treated as read-only.

                The argument dictionary expects the following keys:
                    "search_terms" the query to search for.

        :param sly_data: A dictionary whose keys are defined by the agent hierarchy,
                but whose values are meant to be kept out of the chat stream.

                This dictionary is largely to be treated as read-only.
                It is possible to add key/value pairs to this dict that do not
                yet exist as a bulletin board, as long as the responsibility
                for which coded_tool publishes new entries is well understood
                by the agent chain implementation and the coded_tool implementation
                adding the data is not invoke()-ed more than once.

                Keys expected for this implementation are:
                    None

        :return:
            In case of successful execution:
                The URL to the app as a string.
            otherwise:
                a text string an error message in the format:
                "Error: <error message>"
        """

        # Currently duckduckgo_search does not support async operations
        # Thus, we can only implement it in "invoke".
        # However, asyncio.to_thread method maybe useful here
        # https://docs.python.org/3/library/asyncio-task.html

        search_terms: str = args.get("search_terms", "")
        if search_terms == "":
            return "Error: No search terms provided."

        logger = logging.getLogger(self.__class__.__name__)
        logger.info(">>>>>>>>>>>>>>>>>>>WebsiteSearch>>>>>>>>>>>>>>>>>>")
        logger.info("BSearch Terms: %s", str(search_terms))
        the_links = self.search_web(search_terms, self.top_n)
        links_str = ""
        for index, the_link in enumerate(the_links, start=1):
            links_str += f"{index}. {the_link} ; "
            logger.info("%s. %s", str(index), str(the_link))
        logger.info(">>>>>>>>>>>>>>>>>>>DONE !!!>>>>>>>>>>>>>>>>>>")
        return links_str

    def search_web(self, query: str, num_results: int = 5) -> list:
        """
        Search the web for a given query using DuckDuckGo Search
        and return a list of result URLs.

        :param query: The search query (e.g., "10.5 white men sneakers").
        :param num_results: Number of links to retrieve (default=5).
        :return: List of hyperlink strings.
        """
        # Use duckduckgo_search to retrieve results
        search = DDGS()
        # Synchronous call below!
        # Try to use asynchronous calls for a more performant neuro-san server
        results = search.text(query, max_results=num_results)

        # Extract and return only the URLs from the returned list of dictionaries
        returned_links = [res["href"] for res in results if "href" in res]

        return returned_links
