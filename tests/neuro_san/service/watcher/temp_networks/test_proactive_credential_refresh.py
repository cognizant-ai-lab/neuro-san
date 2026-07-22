
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
"""
Pins credential-rotation behavior on the read path: when the credential
provider already holds a fresh token, an S3 operation must never be
attempted with a stale one.

How botocore handles this natively: a client created WITHOUT explicit
keys holds the session's credentials OBJECT and freezes it per request
at signing time; for token-based sources (IAM Instance Role, ECS Task
Role, SSO) that object is RefreshableCredentials, which checks its
expiry window on every request and refreshes itself BEFORE signing. A
long-lived keyless client therefore never presents an expired token to
S3 - refresh is proactive and costs zero failed calls.
AwsSyncClientWorker relies on exactly this (see its class docstring),
and this test pins both halves of that reliance: the client must be
created keylessly, and no request may go out with a stale token.

A previous design (see issue #1153) instead snapshotted ("froze") the
credentials once and passed the raw key/secret/token strings to
create_client - which makes botocore build a plain static Credentials
object with no refresh machinery. When the token expired, recovery was
REACTIVE: the next S3 call failed with ExpiredToken, and only then was
a new client built from a re-frozen token. Every token-expiry cycle
cost one real failed S3 round trip - on the request path, user-visible
latency plus error-log noise. This test was originally written red
against that design; it is green with keyless clients.
"""
import json
import time

from typing import Any
from typing import Dict
from typing import List
from typing import Tuple

from unittest.mock import patch

from botocore.exceptions import ClientError

from tests.neuro_san.service.watcher.temp_networks.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase
from tests.neuro_san.service.watcher.temp_networks.fake_s3_client import FakeS3Client


class _TokenBoundS3Client:
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
    """

    # pylint: disable=too-few-public-methods

    def __init__(self, fake_s3: FakeS3Client, bound_token: str,
                 provider_state: Dict[str, str],
                 failed_calls: List[Tuple[str, str]]):
        self._fake_s3: FakeS3Client = fake_s3
        self._bound_token: str = bound_token
        self._provider_state: Dict[str, str] = provider_state
        self._failed_calls: List[Tuple[str, str]] = failed_calls

    # pylint: disable=invalid-name
    def get_object(self, Bucket: str, Key: str) -> Dict[str, Any]:
        """
        Reject the request if the token it presents is no longer the
        provider's current token; otherwise delegate to the fake.
        """
        presented_token: str = self._bound_token
        if presented_token is None:
            # Keyless client: the request is signed with the token the
            # provider holds RIGHT NOW, resolved at request time.
            presented_token = self._provider_state["current_token"]

        if presented_token != self._provider_state["current_token"]:
            self._failed_calls.append((presented_token, Key))
            raise ClientError(
                {
                    "Error": {
                        "Code": "ExpiredToken",
                        "Message": "The provided token has expired.",
                    },
                    "ResponseMetadata": {"HTTPStatusCode": 400},
                },
                "GetObject",
            )
        return self._fake_s3.get_object(Bucket=Bucket, Key=Key)

    def close(self):
        """Match the real client lifecycle; nothing to release."""


class TestProactiveCredentialRefresh(S3ReservationsStorageTestBase):
    """
    Verifies that when the credential provider rotates its token between
    two reads, the second read succeeds WITHOUT any S3 call being made
    with the stale token.
    """

    def _put_live_reservation(self, reservation_id: str) -> str:
        """
        Place a well-formed, unexpired reservation object directly into
        the fake bucket so the reader has something real to fetch.

        :return: the reservation id (the reader derives the S3 key from it)
        """
        key: str = f"reservations/{reservation_id}.json"
        self.fake_s3.objects[key] = json.dumps({
            "name": reservation_id,
            "llm_config": {"model_name": "gpt-5.2"},
            "tools": [{"name": reservation_id, "function": {"description": "test frontman"}}],
            "metadata": {
                "reservation": {
                    "id": reservation_id,
                    "lifetime_in_seconds": 3600.0,
                    "expiration_time_in_seconds": time.time() + 3600.0,
                },
                "stored_at": time.time(),
            },
        }).encode("utf-8")
        return reservation_id

    def test_token_rotation_between_reads_causes_no_failed_call(self):
        """
        Scenario: read once while token-1 is valid; the provider then
        rotates to token-2 (token-1 now rejected by S3, as happens on
        the order of an hour for role/STS tokens); read again.

        The provider is healthy the whole time - anything that resolves
        credentials at request time gets a working token. So no S3 call
        should ever be made with the stale one. A keyless long-lived
        client achieves this for free (each request is signed with the
        provider's current token); the old frozen-credentials design
        failed this with exactly one stale-token call recorded, because
        it pinned token-1 into the client without consulting the
        provider again, ate a real ExpiredToken round trip, and only
        then rebuilt and retried.
        """
        reservation_id: str = self._put_live_reservation("copy_cat-rotation")

        provider_state: Dict[str, str] = {"current_token": "token-1"}
        failed_calls: List[Tuple[str, str]] = []
        create_client_kwargs: List[Dict[str, Any]] = []

        def create_token_bound_client(*_args, **kwargs) -> _TokenBoundS3Client:
            # Record HOW the client was created. If explicit keys were
            # passed, capture the pinned token exactly as
            # create_client(aws_session_token=...) pins it into a static
            # Credentials object; a keyless creation leaves it None and
            # the client resolves the provider's token per request.
            create_client_kwargs.append(kwargs)
            return _TokenBoundS3Client(
                self.fake_s3, kwargs.get("aws_session_token"), provider_state, failed_calls,
            )

        # Innermost patch wins over the test base's create_client patch
        # for the duration of this block.
        with patch(
            "neuro_san.service.watcher.temp_networks.aws_sync_client_worker.Session.create_client",
            new=create_token_bound_client,
        ):
            # storage.start() (in setUp) already created the reader worker's
            # long-lived client under the test base's own patch. Discard it
            # so the client serving the reads below is provably created
            # under THIS patch, with the token-checking behavior installed.
            self.storage.reader.retriever.get_sync_client_worker().reset_client()

            reservation, _ = self.storage.get_one_reservation(reservation_id)
            self.assertIsNotNone(
                reservation,
                "Expected the read under token-1 to succeed (control for this test).",
            )

            # The provider rotates: token-1 is now rejected by S3, and
            # anything that resolves credentials at request time gets
            # valid token-2.
            provider_state["current_token"] = "token-2"

            reservation, _ = self.storage.get_one_reservation(reservation_id)
            self.assertIsNotNone(
                reservation,
                "Expected the read after rotation to succeed (proactively or not).",
            )

        self.assertEqual(
            [], failed_calls,
            f"Expected no S3 call to be made with a stale token while the credential "
            f"provider held a fresh one; got stale-token calls {failed_calls}. A "
            f"stale-token call means the client was built from a pinned credential "
            f"snapshot that bypassed the provider and paid a real ExpiredToken round "
            f"trip before recovering - reactive refresh where botocore's "
            f"keyless-client design gives proactive refresh for free.",
        )

        # Mechanism check: the proactive behavior above only holds because the
        # worker creates its client WITHOUT explicit keys - passing any of
        # these arguments makes botocore pin a static credential snapshot
        # into the client and disables at-signing-time refresh.
        explicit_key_args = {"aws_access_key_id", "aws_secret_access_key", "aws_session_token"}
        self.assertGreaterEqual(
            len(create_client_kwargs), 1,
            "Expected at least one client construction under this test's patch; "
            "the reset_client() above should have forced one.",
        )
        for kwargs in create_client_kwargs:
            self.assertFalse(
                explicit_key_args & set(kwargs),
                f"Expected the S3 client to be created without explicit credential "
                f"arguments (keyless), but create_client received "
                f"{sorted(explicit_key_args & set(kwargs))}.",
            )
