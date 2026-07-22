
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
Pins the client-lifecycle cost of the reservation READ path: repeated
reads must reuse one long-lived S3 client, not build and tear one down
per call.

Why it matters: get_one_reservation() runs on the request path -
ExpiringAgentNetworkStorage.get_agent_network_provider() calls it on
every local-cache miss, and on EVERY request naming an unknown agent id
(negative lookups are never cached). A previous design (see issue
#1153) routed every read through a create-client/close cycle that:

  * acquired a worker-wide threading lock,
  * built a brand-new botocore client (~2ms warm, measured - endpoint
    resolution plus a fresh urllib3 pool), serialized under that lock, and
  * close()d the client in a finally block, discarding the connection
    pool - so every S3 GET paid a fresh TCP+TLS handshake and churned
    file descriptors / TIME_WAIT sockets under concurrent load.

Per-call clients are not required for credential correctness either:
AwsSyncClientWorker's long-lived client is created WITHOUT explicit
keys, so each request is signed through the session's
RefreshableCredentials, which botocore refreshes automatically at
signing time. (botocore clients are also thread-safe, so one client can
serve concurrent readers through its connection pool.)

This test was originally written red against the per-call design; it is
green with the long-lived client and guards against regressing to
one-client-per-read.
"""
from unittest.mock import MagicMock

from tests.neuro_san.service.watcher.temp_networks.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


class TestReaderClientReuse(S3ReservationsStorageTestBase):
    """
    Verifies that repeated get_one_reservation() calls share one S3
    client instead of paying client construction and connection-pool
    teardown on every read.
    """

    NUM_READS: int = 5

    def test_repeated_reads_reuse_one_client(self):
        """
        N successful reads of the same reservation should construct
        exactly one S3 client.

        Under the per-call design this failed with create_client called
        N times (once per read): each read built a client under the
        worker lock and close()d it in a finally block, so nothing was
        ever reused.
        """
        reservation_id: str = self._put_live_reservation("copy_cat-reuse")

        # Count client constructions; _fresh_reader_client() re-patches the
        # create_client seam with this mock and discards the client built in
        # setUp, so the constructions counted are exactly the ones the reads
        # below cause.
        create_client_mock = MagicMock(return_value=self.fake_s3)

        with self._fresh_reader_client(create_client_mock):
            for _ in range(self.NUM_READS):
                reservation, agent_network = self.storage.get_one_reservation(reservation_id)
                # Guard against a vacuous pass: every read must actually
                # round-trip the object, or the client count means nothing.
                self.assertIsNotNone(
                    reservation,
                    f"Expected read of {reservation_id} to succeed; reads must work "
                    f"for the client-count assertion below to be meaningful.",
                )
                self.assertIsNotNone(agent_network)

        self.assertEqual(
            1, create_client_mock.call_count,
            f"Expected {self.NUM_READS} reads to share one long-lived S3 client; got "
            f"{create_client_mock.call_count} client constructions. One construction "
            f"per read means each request-path S3 GET pays client build under the "
            f"worker-wide lock plus a fresh TCP+TLS handshake (the connection pool "
            f"dies with each client) - the per-call-client pattern that does not "
            f"scale under concurrent load.",
        )
