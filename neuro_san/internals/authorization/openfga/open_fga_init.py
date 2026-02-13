
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
from typing import Tuple

from logging import getLogger
from logging import Logger

import json
import os
import aiofiles

from openfga_sdk import ClientConfiguration
from openfga_sdk.credentials import CredentialConfiguration
from openfga_sdk.credentials import Credentials
from openfga_sdk.exceptions import FgaValidationException
from openfga_sdk.models.create_store_request import CreateStoreRequest
from openfga_sdk.models.create_store_response import CreateStoreResponse
from openfga_sdk.models.list_stores_response import ListStoresResponse
from openfga_sdk.models.read_authorization_models_response import ReadAuthorizationModelsResponse
from openfga_sdk.models.write_authorization_model_request import WriteAuthorizationModelRequest
from openfga_sdk.models.write_authorization_model_response import WriteAuthorizationModelResponse
from openfga_sdk.client.client import OpenFgaClient


class OpenFgaInit:
    """
    Class to initialize the OpenFGA client where:
        * an OpenFGA store will be created if one does not exist
        * an authorization policy will be uploaded to that store if one does not exist.

    Per the Open FGA docs here:
        https://github.com/openfga/python-sdk?tab=readme-ov-file#initializing-the-api-client

        "We strongly recommend you initialize the OpenFgaClient only once
         and then re-use it throughout your app..."

    ... so this is not to be used by workaday client code.
    Use OpenFgaClientCache.get() instead.
    """

    def __init__(self):
        """
        Constructor.

        This is not to be used by workaday client code.
        Use OpenFgaClientCache.get() instead.
        """
        self.logger: Logger = getLogger(self.__class__.__name__)

    async def initialize_store(self, store_name: str) -> str:
        """
        Initialize a store for general usage.
        This might involve initializing a whole bunch of other stuff if the OpenFGA
        infrastructure has not yet been set up and so is expected to take awhile
        the first time around for any given store_name.
        """
        store_id: str = None
        open_fga_client: OpenFgaClient = self.initialize_one_client(store_id=store_id)
        async with open_fga_client as client:
            open_fga_client, store_id = await self.maybe_initialize_store(client, store_name)

        async with open_fga_client as client:
            await self.prepare_policy(client)
            await self.sync(client)

        return store_id

    @staticmethod
    def initialize_one_client(store_id: str = None, model_id: str = None) -> OpenFgaClient:
        """
        Initializes an OpenFgaClient.  Logic from:
            https://openfga.dev/docs/getting-started/setup-sdk-client

        :param store_id: A specific fact store_id for the client to connect to.
                         Default is None and certain client operations like CreateStore and ListStores
                         do not need a store_id.
        :param authorization_model_id: A default authorization model for the client to use within the store.
                        Can be None. This is OK in certain initialization situations.
                        Many client API calls can have the model_id as part of its request,
                        but to workaday calling code it's much more conventient to have this settled.
        """

        # Get OpenFGA env vars that point to its cloud service.
        # This might also want to come from setup config eventually.
        api_url: str = os.environ.get("FGA_API_URL")
        api_token: str = os.environ.get("FGA_API_TOKEN")

        credentials = None
        if api_token is not None:
            # Checkmarx flags this as a source for Privacy Violation path 2, 3, 4
            # This is a False Positive. Credentials themselves are not leaked anywhere.
            credentials = Credentials(method="api_token",
                                      configuration=CredentialConfiguration(api_token=api_token))
        configuration = ClientConfiguration(api_url=api_url,
                                            store_id=store_id,
                                            authorization_model_id=model_id,
                                            credentials=credentials)

        # Initialize our OpenFGA connection
        fga_client = OpenFgaClient(configuration)

        return fga_client

    async def maybe_initialize_store(self, open_fga_client: OpenFgaClient, store_name: str) \
            -> Tuple[OpenFgaClient, str]:
        """
        Determines whether or not the fact store needs one-time initialization
        from ground-zero.  Logic from:
            https://openfga.dev/docs/getting-started/create-store

        :param open_fga_client: An OpenFgaClient to make the determination about the store
        :param store_name: The name of the store
        :return: Same or different OpenFgaClient that is initialized to talk to the store.
        """

        # Look for our store
        use_store_name: str = os.environ.get("TEST_FGA_STORE_NAME", store_name)
        self.logger.info("Using store name %s", use_store_name)
        store_id: str = None

        # This is the first place that we attempt to connect to the OpenFGA server.
        try:
            response: ListStoresResponse = await open_fga_client.list_stores()

        except FgaValidationException as exception:
            # Make sure the error reflects what is going on better
            raise ValueError("FGA_API_URL env var not set correctly") from exception

        for store in response.stores:
            # store is a openfga_sdk.models.store.Store
            if store.name == use_store_name:
                store_id = store.id
                # Checkmarx flags this as a destination for Privacy Violation path 4
                # This is a False Positive. store ids and names themselves are not actually sensitive information.
                self.logger.info("Found %s for name %s", store_id, use_store_name)
                break

        # Create the store and a new client if not found
        if not store_id:
            body = CreateStoreRequest(name=use_store_name)
            response: CreateStoreResponse = await open_fga_client.create_store(body)
            store_id: str = response.id
            # Checkmarx flags this as a destination for Privacy Violation path 3
            # This is a False Positive. "store_id" itself is not actually sensitive information.
            self.logger.info("Created FGA store id %s", store_id)

        # From here on, always create a new client with the store_id configured
        new_client: OpenFgaClient = self.initialize_one_client(store_id)

        return new_client, store_id

    async def prepare_policy(self, open_fga_client: OpenFgaClient):
        """
        Prepare authorization policy for upload
        By the end of this method the existing open_fga_client member
        will be modified to use the current policy.
        """

        open_fga_policy_file: str = os.environ.get("FGA_POLICY_FILE", "")
        if not open_fga_policy_file:
            # We expect a json containing the auth model policy from the following command:
            # fga model transform --file ${POLICY_FILE_ROOT}.fga | python -m json.tool > ${POLICY_FILE_ROOT}.json
            raise ValueError("FGA_POLICY_FILE env var not set")

        # Read the OpenFGA policy from configuration
        policy: Dict[str, Any] = {}
        async with aiofiles.open(open_fga_policy_file, "r", encoding="utf-8") as policy_file:
            content: str = await policy_file.read()
            policy = json.loads(content)

        found_auth_model: str = await self.find_auth_model(open_fga_client, policy)

        # Do we need to store a new version of the auth model?
        if found_auth_model is None:
            found_auth_model = await self.update_auth_model(open_fga_client, policy)

        # For now. Needs more to set the model up
        # Checkmarx flags this as a destination for Privacy Violation path 1 and 2
        # This is a False Positive. Any auth model id itself is not actually sensitive information.
        self.logger.info("FGA auth model id %s", found_auth_model)

    async def find_auth_model(self, open_fga_client: OpenFgaClient, policy: Dict[str, Any]) -> str:
        """
        Looks for an existing authorization model that matches the
        model_info dictionary in the policy file.
        :param policy: The dictionary from the auth model JSON file
        :return: The AuthorizationModel id for the store that matches the version and
                checksum in the model_info.  If no such model exists, then None
                is returned.
        """
        _ = policy

        # Ask about existing auth models associated with the store
        response: ReadAuthorizationModelsResponse = await open_fga_client.read_authorization_models()

        # Look for the authorization model we specified.
        found_auth_model: str = None

        # Checkmarx flags this as a source for Privacy Violation path 1
        # This is a False Positive. Any auth model id itself is not actually sensitive information.
        auth_model_id: str = os.environ.get("FGA_MODEL_ID")

        # Find the model_info in the json file.
        for auth_model in response.authorization_models:

            # Look for what was specified in the env var (if anything was specified there)
            if auth_model.id == auth_model_id:
                found_auth_model = auth_model.id
                break

            # Callout to allow for self-updating authorization servers
            if await self.is_seen_auth_model(open_fga_client, auth_model.id):
                found_auth_model = auth_model.id

        return found_auth_model

    async def update_auth_model(self, open_fga_client: OpenFgaClient, policy: Dict[str, Any]) -> str:
        """
        Updates the auth model and associates it with the store.
        :param policy: The dictionary from the auth model JSON file
        :return: The AuthorizationModel id for the new model created for the store
        """
        auth_model_id: str = None

        # Find the model_info in the json file.
        model_info: Dict[str, Any] = {}
        model_info = policy.get("model_info", model_info)

        request = WriteAuthorizationModelRequest(
            type_definitions=policy.get("type_definitions"),
            schema_version=policy.get("schema_version"),
            conditions=policy.get("conditions"),
            local_vars_configuration=policy.get("local_vars_configuration"))
        response: WriteAuthorizationModelResponse = \
            await open_fga_client.write_authorization_model(request)
        auth_model_id = response.authorization_model_id

        # Update the model version and checksum now that we've written the model itself.
        # One of the few methods that is not async.
        open_fga_client.set_authorization_model_id(auth_model_id)

        return auth_model_id

    @staticmethod
    async def remove_store_for_testing(open_fga_client: OpenFgaClient):
        """
        Removes the store associated with the given client.
        :param open_fga_client: The client whose store is to be deleted
        """
        if open_fga_client is not None:
            await open_fga_client.delete_store()

    async def sync(self, open_fga_client: OpenFgaClient) -> None:
        """
        Optional method to synchronize the OpenFGA server with any new model changes.
        """
        # Do nothing, but allow overrides for specific circumstances.
        _ = open_fga_client

    async def is_seen_auth_model(self, open_fga_client: OpenFgaClient, auth_model_id: str) -> bool:
        """
        Optional method to allow for self-updating authorization servers
        :param auth_model_id: The auth model id to look for
        :return: True if the auth model was found
        """
        _ = open_fga_client, auth_model_id
        return False
