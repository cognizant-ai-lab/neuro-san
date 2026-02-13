
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

from typing import Any
from typing import Dict
from typing import Type

from os import environ
from threading import Lock

from leaf_common.config.resolver_util import ResolverUtil

# Lazy loading of optional openfga_sdk types.
OpenFgaClient: Type[Any] = ResolverUtil.create_type("openfga_sdk.client.client.OpenFgaClient",
                                                    raise_if_not_found=False,
                                                    install_if_missing="openfga-sdk")


class OpenFgaStoreCache:
    """
    Per the Open FGA docs here:
        https://github.com/openfga/python-sdk?tab=readme-ov-file#initializing-the-api-client

        "We strongly recommend you initialize the OpenFgaClient only once
         and then re-use it throughout your app..."

    Singleton factory for providing client access to OpenFGA server.
    Clients are preserved on a per-thread + per-store basis.

    In production code there will really only ever be a single fact data store
    (DEFAULT_STORE_NAME) for all the threads, but we will want all the threads
    to have their own client.

    In testing, however, we have the opposite: multiple stores for (likely)
    single threaded tests so that they specifically do not stomp on anything
    real code would use.
    """

    # A mapping of store names (like we get in the env var)
    # to store ids (like we get back from the OpenFGA server to initialize clients with).
    store_name_to_id: Dict[str, str] = {}

    # Threaded lock - on purpose even though async access is used
    lock = Lock()

    # Store name to use when none is specified by the caller.
    DEFAULT_STORE_NAME: str = environ.get("FGA_STORE_NAME", "default")

    @classmethod
    async def get_client(cls, store_name: str = None) -> OpenFgaClient:
        """
        :param store_name: The store name to use for fact storage.
                We expect workaday client code to not pass this in, but we allow
                a different store name as an arg so that test code can talk to an
                existing server without messing anything real up.
        :return: a connection to the OpenFGA authorization server for the given store name/
                thread id combination..
        """
        if store_name is None:
            # This allows workaday code to not worry about store names,
            # including when it is called by unit tests.
            store_name = OpenFgaStoreCache.DEFAULT_STORE_NAME

        store_id: str = OpenFgaStoreCache.store_name_to_id.get(store_name)

        # Lazy loading of OpenFgaInit class which directly uses OpenFga SDK types.
        # pylint: disable=import-outside-toplevel
        from neuro_san.internals.authorization.openfga.open_fga_init import OpenFgaInit

        if store_id is None:
            # Note: Synchronous lock is required here
            init = OpenFgaInit()
            with OpenFgaStoreCache.lock:
                store_id = await init.initialize_store(store_name)
                OpenFgaStoreCache.store_name_to_id[store_name] = store_id

        fga_client: OpenFgaClient = OpenFgaInit.initialize_one_client(store_id=store_id)

        return fga_client

    @classmethod
    def _remove_key_for_testing(cls, store_name: str):
        """
        Removes a store_name key for testing purposes only.

        :param store_name: The store name to use for fact storage.
        :param remove_from_map: When True the entry will be
                removed from the store-name/thread map.
        """

        # Do not hold the lock as the caller will be holding for us.
        store_id: str = OpenFgaStoreCache.store_name_to_id.get(store_name)
        if store_id is not None:

            # Do not actually remove the default store as that is what the app
            # will be using. Remove any other store for testing though.
            if OpenFgaStoreCache.DEFAULT_STORE_NAME != store_name:
                del OpenFgaStoreCache.store_name_to_id[store_name]

    @classmethod
    def reset_for_testing(cls):
        """
        Reset the instance for testing purposes only.
        """
        with OpenFgaStoreCache.lock:

            if len(OpenFgaStoreCache.store_name_to_id) > 0:

                # Close all the clients registered in the map
                # Need to add remove_from_map=False or else will get this error:
                #        "RuntimeError: dictionary changed size during iteration"
                # pylint: disable=consider-iterating-dictionary
                for store_name in cls.store_name_to_id.keys():
                    cls._remove_store_name_for_testing(store_name)

                # Clear the map separately
                cls.store_name_to_id = {}
