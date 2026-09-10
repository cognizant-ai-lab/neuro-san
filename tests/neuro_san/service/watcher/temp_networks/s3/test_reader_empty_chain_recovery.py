
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
Pins recovery on the reservation READ path when the credential chain
resolves to NOTHING mid-rotation (e.g. a credentials file caught empty
while another process rewrites it).

This is the other face of the rotation window the ExpiredToken /
InvalidToken retry rides out: instead of S3 rejecting a request signed
with stale credentials (a ClientError), botocore itself raises
NoCredentialsError - a BotoCoreError - from the sync worker's
empty-chain guard in get_client(). A retry gate written as
"except ClientError" never sees that exception, so it would escape
retry_with_new_client with retry budget unused, sail past the reader's
ClientError/JSONDecodeError handlers, and fail the user's request
outright - even though the rewrite lands a second later and the loop
had backoff attempts to spare.

The widened gate catches NoCredentialsError/PartialCredentialsError
alongside ClientError and classifies them via
S3Util.is_credential_rejection_error: back off, let botocore re-resolve
the chain (a None resolution is never cached), and retry. Without the
widening, the recovery test below fails with NoCredentialsError
propagating out of get_one_reservation() after a single resolution.
"""
from unittest.mock import patch

from tests.neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


class TestReaderEmptyChainRecovery(S3ReservationsStorageTestBase):
    """
    Verifies that a read hitting an empty credential chain backs off,
    re-resolves, and succeeds, instead of crashing the request path with
    an uncaught NoCredentialsError.
    """

    def test_empty_chain_triggers_retry_and_read_succeeds(self):
        """
        Scenario: the reader needs a client while the credential chain
        momentarily resolves to None (credentials file mid-rewrite); by
        the retry's second resolution the rewrite has landed.

        Expected: get_client()'s empty-chain guard raises
        NoCredentialsError, the credential retry treats it as a
        credential rejection (no poisoned client is cached), and the
        next attempt's re-resolution succeeds - so the read returns the
        reservation. If NoCredentialsError is not gated (a
        ClientError-only retry), it propagates out of
        get_one_reservation() after a single chain resolution and this
        test errors instead of passing.
        """
        reservation_id: str = self._put_live_reservation("copy_cat-empty-chain")

        resolutions = {"count": 0}

        def resolve_chain_mid_rewrite(*_args, **_kwargs):
            resolutions["count"] += 1
            if resolutions["count"] == 1:
                # The rotation's rewrite has the file empty right now.
                return None
            # The rewrite landed; the chain resolves real credentials
            # again. get_client() only checks "is None", so any sentinel
            # models resolved credentials.
            return object()

        def create_client_healthy(*_args, **_kwargs):
            return self.fake_s3

        # sync_sleep is patched so the retry's jittered backoff does not
        # slow the test down; recovery behavior is unaffected.
        with self._fresh_reader_client(create_client_healthy), patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_sync_client_worker.Session.get_credentials",
            new=resolve_chain_mid_rewrite,
        ), patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_sync_client_worker.sync_sleep"
        ):
            reservation, agent_network = self.storage.get_one_reservation(reservation_id)

        self.assertIsNotNone(
            reservation,
            "Expected the read to recover from an empty credential chain by "
            "backing off and re-resolving. A crash or None reservation means "
            "NoCredentialsError escaped the credential retry - the request "
            "fails during the exact rotation window the retry was built for.",
        )
        self.assertIsNotNone(agent_network)
        self.assertGreaterEqual(
            resolutions["count"], 2,
            f"Expected at least 2 credential-chain resolutions (the empty one "
            f"plus the retry's re-resolution after the rewrite landed); got "
            f"{resolutions['count']}. A single resolution means the "
            f"NoCredentialsError was never retried.",
        )
