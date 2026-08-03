
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
Pins the expiration sweep's policy for objects under the reservations/
prefix whose bodies are valid JSON but are NOT shaped like a reservation
(no metadata.reservation dict with a numeric expiration_time_in_seconds).

Such objects are how the "'NoneType' object has no attribute 'get'"
errors reported from production arise: the bucket is long-lived and
shared across code versions, so it can contain objects written by an
older schema, by other tooling, or by a since-fixed writer bug.

Three policies were considered before the current one:

  1. Raise: the sweep crashes at the first malformed key, the watcher
     retries next interval and crashes at the same key again - so ONE
     bad object stops ALL expiration, forever, while logging the
     NoneType error every cycle.
  2. Treat as expired and delete immediately: DictionaryExtractor
     defaults make a missing expiration_time read as 0, current_time > 0
     is always true, and the object is PERMANENTLY DELETED with only a
     debug-level log naming reservation '<unknown>'. That silently
     destroys any object the current code merely fails to understand
     (e.g. schema drift during a rolling deploy, where an old server's
     sweep would delete a new server's live reservations), and it
     destroys the only evidence of whatever wrote the bad object.
  3. Skip and warn forever: safe for the data and the sweep, but
     unparseable detritus builds up and gets re-read and re-logged on
     every pass (review feedback on the first draft of this policy).

The pinned policy is AGE-GATED deletion: an unparseable object is
skipped with a WARNING while younger than
S3ReservationsExpiration.MALFORMED_OBJECT_GRACE_SECONDS, and deleted
with a WARNING once older. Every reservation has a bounded lifetime, so
an object older than any possible lifetime cannot be a live reservation
under ANY schema version - deleting it is safe and bounds the detritus,
while the grace window keeps rolling-deploy schema drift from
destroying live reservations and gives humans time to notice the
warnings.

NOTE on coverage vs the alternatives: immediate deletion (policy 2)
fails test_young_wrong_shape_object_is_not_deleted; skip-forever
(policy 3) fails test_old_wrong_shape_object_is_deleted; raising
(policy 1) fails test_null_reservation_object_does_not_kill_sweep,
because DictionaryExtractor returns a stored JSON null in preference to
its default, which put naive extractor-based handling right back into
policy 1's death spiral.
"""
import json
import time

from datetime import datetime
from datetime import timedelta
from datetime import timezone

from typing import Any

from botocore.exceptions import ClientError

from neuro_san.service.watcher.temp_networks.s3.s3_reservations_expiration import S3ReservationsExpiration

from tests.neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


class TestExpirationMalformedObjectPolicy(S3ReservationsStorageTestBase):
    """
    Verifies that expire_reservations() survives objects that are not
    shaped like reservations, keeps expiring well-formed reservations
    around them, and applies the age-gated policy to them: skip and
    WARN while the object is younger than the grace period, delete with
    a WARNING once it is older than any reservation could live.
    """

    def _put_json_object(self, key: str, payload: Any):
        """
        Place an arbitrary JSON body directly into the fake bucket,
        bypassing the writer. This models the real-world source of
        malformed objects: content already in the bucket that the
        CURRENT writer did not produce (older schema versions, other
        tooling, since-fixed bugs).
        """
        self.fake_s3.objects[key] = json.dumps(payload).encode("utf-8")

    def _put_reservation_object(self, reservation_id: str, expires_in_seconds: float) -> str:
        """
        Place a well-formed reservation object (matching the writer's
        on-disk schema) directly into the fake bucket.

        :param expires_in_seconds: offset from now; negative = already expired
        :return: the S3 object key used
        """
        key: str = f"reservations/{reservation_id}.json"
        self._put_json_object(key, {
            "name": reservation_id,
            "metadata": {
                "reservation": {
                    "id": reservation_id,
                    "lifetime_in_seconds": 3600.0,
                    "expiration_time_in_seconds": time.time() + expires_in_seconds,
                },
                "stored_at": time.time(),
            },
        })
        return key

    def test_control_expired_reservation_is_deleted(self):
        """
        Control case anchoring the harness: with only well-formed objects
        in the bucket, the sweep deletes the expired one and keeps the
        live one. This test passes under any of the candidate policies;
        it exists so that failures in the sibling tests are attributable
        to the malformed-object policy, not to the test scaffolding.
        """
        expired_key: str = self._put_reservation_object("copy_cat-expired", -3600.0)
        live_key: str = self._put_reservation_object("copy_cat-live", +3600.0)

        self.storage.expiration.expire_reservations()

        self.assertNotIn(
            expired_key, self.fake_s3.objects,
            f"Expected the expired reservation {expired_key} to be deleted by the sweep.",
        )
        self.assertIn(
            live_key, self.fake_s3.objects,
            f"Expected the live reservation {live_key} to survive the sweep.",
        )

    def test_young_wrong_shape_object_is_not_deleted(self):
        """
        A valid-JSON object under the prefix with no metadata.reservation
        block must NOT be deleted while it is younger than the grace
        period (the fake stamps direct inserts as freshly written).

        Guards against the immediate-delete policy, where
        DictionaryExtractor defaults classify the object as "expired at
        epoch 0" (current_time > 0 is always true) and delete_object
        permanently removes it, logging only at debug level as
        reservation '<unknown>'. "We could not parse it" and "it has
        expired" are different facts; conflating them silently destroys
        any object written by a schema the current code doesn't know -
        including live reservations written by a newer server version
        during a rolling deploy, which are by definition younger than
        the grace period.
        """
        wrong_shape_key: str = "reservations/wrong-shape.json"
        self._put_json_object(wrong_shape_key, {
            "foo": "bar",
            "note": "valid JSON, but not shaped like a reservation",
        })
        live_key: str = self._put_reservation_object("copy_cat-live", +3600.0)

        self.storage.expiration.expire_reservations()

        self.assertIn(
            wrong_shape_key, self.fake_s3.objects,
            f"Expected the unparseable object {wrong_shape_key} to be left in place "
            f"while younger than the grace period; it was deleted, meaning the sweep "
            f"treats 'could not parse' as 'expired' and silently destroys data.",
        )
        self.assertIn(
            live_key, self.fake_s3.objects,
            f"Expected the live reservation {live_key} to survive the sweep.",
        )

    def test_old_wrong_shape_object_is_deleted(self):
        """
        An unparseable object OLDER than the grace period must be
        deleted by the sweep (with a WARNING).

        Guards against the skip-forever policy: every reservation has a
        bounded lifetime, so an object last modified longer ago than any
        reservation could live cannot be a live reservation under ANY
        schema version. Leaving it would mean unparseable detritus
        builds up and gets re-read and re-logged on every pass, forever.
        """
        old_key: str = "reservations/old-wrong-shape.json"
        self._put_json_object(old_key, {
            "foo": "bar",
            "note": "valid JSON, but not shaped like a reservation",
        })
        # Backdate the object to just past the grace period.
        self.fake_s3.last_modified[old_key] = (
            datetime.now(timezone.utc)
            - timedelta(seconds=S3ReservationsExpiration.MALFORMED_OBJECT_GRACE_SECONDS + 3600.0)
        )
        live_key: str = self._put_reservation_object("copy_cat-live", +3600.0)

        self.storage.expiration.expire_reservations()

        self.assertNotIn(
            old_key, self.fake_s3.objects,
            f"Expected the unparseable object {old_key}, last modified beyond the "
            f"grace period, to be deleted; leaving it means detritus accumulates "
            f"and is re-read and re-logged on every sweep.",
        )
        self.assertIn(
            live_key, self.fake_s3.objects,
            f"Expected the live reservation {live_key} to survive the sweep.",
        )

    def test_object_deleted_mid_check_counts_as_expired(self):
        """
        Race: another process deletes an unparseable object between the
        sweep's get_object and the head_object age check.

        HEAD signals a missing key with the bare HTTP code "404" - a HEAD
        response has no body to carry a NoSuchKey code - so the sweep
        must treat "404" the same as NoSuchKey: the object is gone, which
        is the desired outcome for expiration, not an error to log.
        """
        racing_key: str = "reservations/racing.json"
        self._put_json_object(racing_key, {"foo": "bar"})

        def head_object_racing_delete(**_kwargs):
            # Simulate the concurrent deletion: the object vanishes just
            # before the HEAD lands, exactly as real S3 would report it.
            raise ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}},
                "HeadObject",
            )

        # Inject onto the in-memory FakeS3Client for the duration of this
        # test only (instance attribute shadows the class method).
        self.fake_s3.head_object = head_object_racing_delete

        expired: bool = self.storage.expiration.expire_one_reservation(
            racing_key, time.time(), sync_aws_client=self.fake_s3)

        self.assertTrue(
            expired,
            "Expected a 404 from the head_object age check to be treated as "
            "'already removed by another process' (a successful expiration "
            "outcome), not logged as an S3 error.",
        )

    def test_null_expiration_time_is_treated_as_malformed(self):
        """
        What happens if expiration_time_in_seconds is None (a stored JSON
        null)? Answer: extract_reservation_data() rejects the whole
        payload (null fails its isinstance check, and DictionaryExtractor
        would otherwise return the stored null in preference to any
        default), so the object takes the malformed path - skipped while
        young - and the sweep's current_time > expiration_time comparison
        can never see a None. No crash, no deletion, and reservations
        after it still expire.
        """
        null_expiration_key: str = "reservations/a-null-expiration.json"
        self._put_json_object(null_expiration_key, {
            "name": "null-expiration",
            "metadata": {
                "reservation": {
                    "id": "null-expiration",
                    "lifetime_in_seconds": 3600.0,
                    "expiration_time_in_seconds": None,
                },
                "stored_at": time.time(),
            },
        })
        expired_key: str = self._put_reservation_object("z-expired", -3600.0)

        self.storage.expiration.expire_reservations()

        self.assertIn(
            null_expiration_key, self.fake_s3.objects,
            f"Expected the null-expiration object {null_expiration_key} to be "
            f"treated as malformed (skipped while young), not deleted and not a "
            f"crash: 'time() > None' must be unreachable.",
        )
        self.assertNotIn(
            expired_key, self.fake_s3.objects,
            f"Expected the expired reservation {expired_key} to be deleted even "
            f"though a null-expiration object sorts before it in the sweep.",
        )

    def test_null_reservation_object_does_not_kill_sweep(self):
        """
        An object whose body is {"metadata": {"reservation": null}} must
        not abort the sweep, and reservations that sort after it must
        still be expired.

        Guards against the stored-null trap: DictionaryExtractor.get()
        only applies its default when a key is MISSING; a key present
        with a stored JSON null is returned as None in preference to
        the default, so naive extractor-based handling calls
        reservation_data.get(...) on None and crashes with
        AttributeError: 'NoneType' object has no attribute 'get' - the
        exact error reported from production.

        The consequences mirror that original report: the watcher
        re-runs the sweep every interval and crashes at the same key
        each time, so the expired reservation behind the poison object
        (and everything else in the bucket) is never cleaned up until a
        human deletes the poison object by hand.

        Key names matter here: "a-poison" sorts lexicographically before
        "z-expired" (matching real S3 listing order, which the fake
        mirrors), guaranteeing the sweep meets the poison object first.
        """
        poison_key: str = "reservations/a-poison.json"
        self._put_json_object(poison_key, {"metadata": {"reservation": None}})
        expired_key: str = self._put_reservation_object("z-expired", -3600.0)

        # If the stored-null case regresses, this call raises AttributeError
        # out of retry_with_new_client (which only handles ClientError),
        # failing this test at the call site - before any assertion below.
        self.storage.expiration.expire_reservations()

        self.assertNotIn(
            expired_key, self.fake_s3.objects,
            f"Expected the expired reservation {expired_key} to be deleted even though "
            f"a poison object ({poison_key}) sorts before it in the sweep.",
        )
        self.assertIn(
            poison_key, self.fake_s3.objects,
            f"Expected the unparseable object {poison_key} to be left in place "
            f"(young: still within the grace period), not deleted.",
        )
