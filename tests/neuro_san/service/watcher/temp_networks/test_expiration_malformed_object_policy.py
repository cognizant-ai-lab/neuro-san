
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

Three policies are possible when the sweep meets such an object, and the
codebase has already shipped two of them:

  1. Raise: the sweep crashes at the first malformed key, the watcher
     retries next interval and crashes at the same key again - so ONE
     bad object stops ALL expiration, forever, while logging the
     NoneType error every cycle.
  2. Treat as expired and delete: DictionaryExtractor defaults make a
     missing expiration_time read as 0, current_time > 0 is always
     true, and the object is PERMANENTLY DELETED with only a
     debug-level log naming reservation '<unknown>'.
     That silently destroys any object the current code merely fails to
     understand (e.g. schema drift during a rolling deploy, where an old
     server's sweep would delete a new server's live reservations), and
     it destroys the only evidence of whatever wrote the bad object.
  3. Skip and warn (the policy these tests pin): the sweep must survive
     the object, must keep expiring everything else, and must NOT delete
     data it cannot parse - deleting data should be a human decision,
     not a parse failure. The cost is that true garbage lingers and
     warns every sweep until someone removes it.

NOTE: test_wrong_shape_object_is_not_deleted and
test_null_reservation_object_does_not_kill_sweep fail under either of
the first two policies - by design. The first pins against policy 2's
silent deletion; the second shows that policy 2 does not even fully
stop the reported NoneType error, because DictionaryExtractor returns
a stored JSON null in preference to its default, putting the sweep
right back into policy 1's death spiral.
"""
import json
import time

from typing import Any

from tests.neuro_san.service.watcher.temp_networks.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


class TestExpirationMalformedObjectPolicy(S3ReservationsStorageTestBase):
    """
    Verifies that expire_reservations() survives objects that are not
    shaped like reservations, keeps expiring well-formed reservations
    around them, and never deletes an object it could not parse.
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
        live one. This test passes under any of the three candidate
        policies; it exists so that failures in the sibling tests are
        attributable to the malformed-object policy, not to the test
        scaffolding.
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

    def test_wrong_shape_object_is_not_deleted(self):
        """
        A valid-JSON object under the prefix with no metadata.reservation
        block must NOT be deleted by the sweep.

        Guards against the treat-as-expired-and-delete policy, where
        DictionaryExtractor defaults classify the object as "expired at
        epoch 0" (current_time > 0 is always true) and delete_object
        permanently removes it, logging only at debug level as
        reservation '<unknown>'. "We could not parse it" and "it has expired" are
        different facts; conflating them silently destroys any object
        written by a schema the current code doesn't know - including
        live reservations written by a newer server version during a
        rolling deploy.
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
            f"(skip-and-warn policy); it was deleted, meaning the sweep treats "
            f"'could not parse' as 'expired' and silently destroys data.",
        )
        self.assertIn(
            live_key, self.fake_s3.objects,
            f"Expected the live reservation {live_key} to survive the sweep.",
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
            f"(skip-and-warn policy), not deleted.",
        )
