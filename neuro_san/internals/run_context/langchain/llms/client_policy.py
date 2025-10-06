
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

import os

from langchain.llms.base import BaseLanguageModel


class ClientPolicy:
    """
    Policy interface to manage the lifecycles of web clients that talk to LLM services.

    There are really two styles of implementation encompassed by this one interface.

    1) When BaseLanguageModels can have web clients passed into their constructor,
       implementations should use the create_client() method to retain any references necessary
       to help them clean up nicely in the delete_resources() method.

    2) When BaseLanguageModels cannot have web clients passed into their constructor,
       implementations should pass the already created llm into their implementation's
       constructor. Later delete_resources() implementations will need to do a reach-in
       to the llm instance to clean up any references related to the web client.
    """

    def __init__(self, llm: BaseLanguageModel = None):
        """
        Constructor.

        :param llm: BaseLanguageModel
        """
        self.llm: BaseLanguageModel = llm

    # pylint: disable=useless-return
    def create_client(self, config: Dict[str, Any]) -> Any:
        """
        Creates the web client to used by a BaseLanguageModel to be
        constructed in the future.  Neuro SAN infrastructures prefers that this
        be an asynchronous client, however we realize some BaseLanguageModels
        do not support that (even though they should!).

        Implementations should retain any references to state that needs to be cleaned up
        in the delete_resources() method.

        :param config: The fully specified llm config
        :return: The web client that accesses the LLM.
                By default this is None, as many BaseLanguageModels
                do not allow a web client to be passed in as an arg.
        """
        _ = config
        return None

    async def delete_resources(self):
        """
        Release the run-time resources used by the instance.

        Unfortunately for many BaseLanguageModels, this tends to involve
        a reach-in to its private internals in order to shutting down
        any web client references in there.
        """
        raise NotImplementedError

    def get_value_or_env(self, config: Dict[str, Any], key: str, env_key: str,
                         none_obj: Any = None) -> Any:
        """
        :param config: The config dictionary to search
        :param key: The key for the config to look for
        :param env_key: The os.environ key whose value should be gotten if either
                        the key does not exist or the value for the key is None
        :param none_obj:  An optional object instance to test.
                          If present this method will return None, implying
                          that some other external object/mechanism is supplying the values.
        """
        if none_obj is not None:
            return None

        value = None
        if config is not None:
            value = config.get(key)

        if value is None and env_key is not None:
            value = os.getenv(env_key)

        return value
