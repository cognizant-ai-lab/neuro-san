
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
from typing import List
from typing import Optional
from typing import Tuple

from tests.neuro_san.service.watcher.temp_networks.s3.fake_s3_client import FakeS3Client
from tests.neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


class TokenBoundS3Client:
    """
    Wraps the in-memory FakeS3Client with token checking, modeling how
    real S3 evaluates the credentials each request was signed with -
    for BOTH of botocore's client-creation modes:

      * explicit keys passed to create_client() pin a static token into
        the client forever (bound_token is that pinned token), while
      * a keyless client (bound_token is None) signs each request by
        freezing the session's credentials AT REQUEST TIME, so it
        presents whatever token the provider currently holds
        (RefreshableCredentials behavior).

    Any request presenting a token other than the provider's current one
    fails with ExpiredToken - exactly the HTTP 400 boto3 surfaces for a
    stale STS/role token.

    Used by TestS3ReservationsReader.test_token_rotation_between_reads_causes_no_failed_call.
    Like FakeS3Client, this module does not start with "test_", so pytest does
    not collect it.
    """

    def __init__(self, fake_s3: FakeS3Client, bound_token: Optional[str],
                 provider_state: Dict[str, str],
                 failed_calls: List[Tuple[str, str]]) -> None:
        """
        Bind the fake bucket and the credential state this client was created under.

        :param fake_s3: The in-memory FakeS3Client that accepted requests are delegated to
        :param bound_token: The session token pinned into this client at creation time,
                or None when the client was created keylessly and therefore resolves
                the provider's current token on every request
        :param provider_state: Shared mutable dict whose "current_token" entry is the
                token the credential provider holds right now; the test rotates it
                between reads
        :param failed_calls: Shared list that every stale-token request is appended
                to as a (presented_token, key) tuple, so the test can assert that
                none happened
        """
        self._fake_s3: FakeS3Client = fake_s3
        # None means "created keylessly" - see class docstring.
        self._bound_token: Optional[str] = bound_token
        self._provider_state: Dict[str, str] = provider_state
        self._failed_calls: List[Tuple[str, str]] = failed_calls

    # pylint: disable=invalid-name
    def get_object(self, Bucket: str, Key: str) -> Dict[str, Any]:
        """
        Reject the request if the token it presents is no longer the
        provider's current token; otherwise delegate to the fake.

        :param Bucket: The S3 bucket name (boto3's PascalCase keyword argument)
        :param Key: The S3 object key (boto3's PascalCase keyword argument)
        :return: The fake's get_object response, a dict with a "Body" stream
        :raises ClientError: ExpiredToken when the presented token is stale
        """
        presented_token: Optional[str] = self._bound_token
        if presented_token is None:
            # Keyless client: the request is signed with the token the
            # provider holds RIGHT NOW, resolved at request time.
            presented_token = self._provider_state["current_token"]

        if presented_token != self._provider_state["current_token"]:
            self._failed_calls.append((presented_token, Key))
            raise S3ReservationsStorageTestBase.make_expired_token_error("GetObject")
        return self._fake_s3.get_object(Bucket=Bucket, Key=Key)
