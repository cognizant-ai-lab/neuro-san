
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
S3ReservationsStorage accepts a configurable prefix (default
"reservations/") that's prepended to every reservation's S3 object
key. Production deploys may set a non-default prefix for
multi-tenancy, environment separation (prod/staging), or version
migration. This module verifies that add_reservations writes objects
under the configured prefix - catching regressions where the prefix
is hardcoded or otherwise dropped.
"""
import pytest

from neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage \
    import S3ReservationsStorage

from tests.neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


class TestCustomPrefix(S3ReservationsStorageTestBase):
    """
    Existing tests T1-T9 all use the default prefix "reservations/".
    None of them detect a hardcoded-prefix regression in
    get_obj_key_for_reservation, because the hardcoded value matches
    the default by coincidence. This test exercises a non-default
    prefix to surface that class of bug.
    """

    @pytest.mark.asyncio
    async def test_add_uses_configured_prefix_for_object_keys(self):
        """
        A storage configured with a non-default prefix writes objects
        under that prefix and not under the default. Catches
        regressions where get_obj_key_for_reservation hardcodes the
        default prefix or drops self.prefix entirely.
        """
        # Construct a fresh storage with a non-default prefix. The
        # boto3_client patch installed by S3ReservationsStorageTestBase
        # is still active, so start() will pick up the same FakeS3Client
        # the base setUp built. Sharing the FakeS3Client lets us inspect
        # the writes directly without standing up a second mock.
        custom_prefix = "my-tenant/reservations-v2/"
        custom_storage = S3ReservationsStorage(
            bucket_name="test-bucket",
            prefix=custom_prefix,
        )
        custom_storage.start()

        reservation_id = "copy_cat-test-UUID-0010"
        reservation = self._make_reservation(reservation_id, lifetime_seconds=600.0)
        agent_spec = self._make_agent_spec("copy_cat")

        await custom_storage.add_reservations({reservation: agent_spec})

        # Exactly one object in S3. Catches accidental no-op writes and
        # any "writes to multiple keys" regression that splatters the
        # bucket.
        self.assertEqual(
            1,
            len(self.fake_s3.objects),
            f"Expected exactly one S3 object after the custom-prefix "
            f"write; bucket has {list(self.fake_s3.objects)}.",
        )

        # The object's key uses the configured custom prefix. Catches
        # the canonical hardcoded-prefix bug: the default value is
        # baked into the key helper instead of self.prefix being read.
        expected_key = f"{custom_prefix}{reservation_id}.json"
        self.assertIn(
            expected_key,
            self.fake_s3.objects,
            f"Expected object at custom-prefix key {expected_key!r}; "
            f"found {list(self.fake_s3.objects)}. The storage is not "
            f"honoring the configured prefix.",
        )

        # Belt-and-suspenders: the object is NOT at the default-prefix
        # key. Catches a "writes to BOTH the custom AND the default"
        # double-write bug that the assertEqual(1, ...) check above
        # would also catch, but this assertion gives a clearer message
        # specifically for that failure mode.
        default_prefix_key = f"reservations/{reservation_id}.json"
        self.assertNotIn(
            default_prefix_key,
            self.fake_s3.objects,
            f"Object unexpectedly found at default-prefix key "
            f"{default_prefix_key!r}; the storage is writing under the "
            f"default prefix instead of (or in addition to) the "
            f"configured custom prefix.",
        )
