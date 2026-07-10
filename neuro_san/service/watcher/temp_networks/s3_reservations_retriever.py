
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

from os import getenv
from functools import partial

from json import loads
from logging import getLogger
from logging import Logger

from boto3 import client as boto3_client
from botocore.client import BaseClient
from botocore.exceptions import ClientError
from botocore.exceptions import NoCredentialsError

from neuro_san.service.watcher.temp_networks.s3_retry_util import S3RetryUtil


class S3ReservationsRetriever:
    """
    AWS S3-based implementation of ReservationsStorage.

    Stores reservations as JSON objects in an S3 bucket, with each reservation
    stored in its associated agent spec as metadata.
    """

    def __init__(self, name: str = "S3ReservationsRetriever", bucket_name: str = "", prefix: str = "reservations/"):
        """
        Initialize S3 reservations storage.

        :param bucket_name: S3 bucket name (defaults to AGENT_RESERVATIONS_S3_BUCKET env var)
        :param prefix: S3 key prefix for reservation objects
        :param check_expirations_interval_seconds: How often to check for expired reservations.
                                    If 0 or negative, expiration checks are disabled.
        """
        # Our default for check_expirations_interval_seconds is 0
        # because S3 expiration check is generally a significant execution load,
        # and we may want to run it externally on demand rather than on a fixed schedule inside the service.
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.name: str = name

        # Configure bucket name from parameter or environment variable
        env_bucket: str = getenv("AGENT_RESERVATIONS_S3_BUCKET", "")
        self.bucket_name: str = bucket_name or env_bucket
        if not self.bucket_name:
            raise ValueError(
                "S3 bucket name must be provided via bucket_name parameter or "
                "AGENT_RESERVATIONS_S3_BUCKET environment variable"
            )

        # Set up S3 key prefix and initialize sync target
        self.prefix: str = prefix
        self.client: BaseClient = None

    def get_prefix(self) -> str:
        """
        :return: The S3 key prefix for reservation objects.
        """
        return self.prefix

    def get_bucket_name(self) -> str:
        """
        :return: The S3 bucket name.
        """
        return self.bucket_name

    def get_client(self) -> BaseClient:
        """
        :return: The synchronous S3 client.
        """
        return self.client

    def start(self):
        """
        Initialize the S3 client and validate connection to the bucket.

        This method can be called to re-initialize the connection if needed.
        """
        try:
            # Initialize S3 client using default AWS credential chain
            # DEF - these are long-lived. What if credentials expire?
            self.client = boto3_client("s3")

            # Validate bucket exists and we have access by performing a head operation
            self.client.head_bucket(Bucket=self.bucket_name)
            self.logger.info("%s: Successfully connected to S3 bucket: %s", self.name, self.bucket_name)

        except NoCredentialsError as exception:
            # Handle missing AWS credentials
            raise ValueError(f"{self.name}: AWS credentials not found. Please configure AWS credentials.") \
                from exception
        except ClientError as exception:
            # Handle various S3 access errors with specific messages
            error_code: str = exception.response["Error"]["Code"]
            if error_code == "404":
                raise ValueError(f"{self.name}: S3 bucket '{self.bucket_name}' does not exist") from exception
            if error_code == "403":
                raise ValueError(f"{self.name}: Access denied to S3 bucket '{self.bucket_name}'") from exception
            raise ValueError(f"{self.name}: Error accessing S3 bucket '{self.bucket_name}': {exception}") \
                from exception

    def retrieve_object_with_retries(self, obj_key: str, source: str = None) -> Dict[str, Any]:
        """
        Helper method to retrieve an S3 object with retries.
        :param obj_key: S3 object key to retrieve
        :return: The parsed JSON content of the S3 object as a dictionary
        :raises: ClientError if the object cannot be retrieved after retries
                 JSONDecodeError if the content cannot be parsed as JSON
        """
        get_function = partial(self.client.get_object, Bucket=self.bucket_name, Key=obj_key)
        if source is None:
            source = self.name
        obj_response: Dict[str, Any] = S3RetryUtil.do_with_retries(source, get_function)
        # Parse JSON content from S3 object body
        json_content: str = obj_response["Body"].read().decode("utf-8")
        return loads(json_content)
