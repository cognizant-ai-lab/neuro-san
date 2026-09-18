
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

from tests.neuro_san.service.watcher.temp_networks.s3.fake_s3_client import FakeS3Client
from tests.neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


class InvalidTokenS3Client:
    """
    Wraps the in-memory FakeS3Client with a client-construction-time
    credential state: a client built while the state is bad rejects every
    request with InvalidToken (as real S3 does when a request is signed
    with a malformed/mismatched token), and a client built after the
    credential chain re-resolved delegates normally.

    Used by TestS3ReservationsReader.test_invalid_token_triggers_rebuild_and_read_succeeds.
    Like FakeS3Client, this module does not start with "test_", so pytest does
    not collect it.
    """

    def __init__(self, fake_s3: FakeS3Client, bad: bool) -> None:
        """
        Bind the fake bucket and freeze the credential state this client was built from.

        :param fake_s3: The in-memory FakeS3Client that accepted requests are delegated to
        :param bad: True when the credential state at construction time is bad, so
                every request this client makes is rejected with InvalidToken;
                False to delegate every request to the fake
        """
        self._fake_s3: FakeS3Client = fake_s3
        self._bad: bool = bad

    # pylint: disable=invalid-name
    def get_object(self, Bucket: str, Key: str) -> Dict[str, Any]:
        """
        Reject with InvalidToken while this client's credential state is
        bad; otherwise delegate to the fake.

        :param Bucket: The S3 bucket name (boto3's PascalCase keyword argument)
        :param Key: The S3 object key (boto3's PascalCase keyword argument)
        :return: The fake's get_object response, a dict with a "Body" stream
        :raises ClientError: InvalidToken while the credential state is bad
        """
        if self._bad:
            raise S3ReservationsStorageTestBase.make_client_error("InvalidToken")
        return self._fake_s3.get_object(Bucket=Bucket, Key=Key)
