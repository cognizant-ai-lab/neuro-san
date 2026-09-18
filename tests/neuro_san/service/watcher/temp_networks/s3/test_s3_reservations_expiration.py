
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
import json
import time

from datetime import datetime
from datetime import timedelta
from datetime import timezone

from functools import partial

from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import NoReturn
from typing import Optional

from unittest.mock import MagicMock
from unittest.mock import patch

from botocore.exceptions import ClientError

from neuro_san.service.watcher.temp_networks.s3.s3_reservations_expiration import S3ReservationsExpiration

from tests.neuro_san.service.watcher.temp_networks.s3.fake_s3_client import FakeS3Client
from tests.neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


class TestS3ReservationsExpiration(S3ReservationsStorageTestBase):
    """
    Unit tests for S3ReservationsExpiration, reached directly as
    self.storage.expiration on the S3ReservationsStorage that
    S3ReservationsStorageTestBase wires to an in-memory fake S3 client.

    Most of this class pins the expiration sweep's policy for objects under
    the reservations/ prefix whose bodies are valid JSON but are NOT shaped
    like a reservation (no metadata.reservation dict with a numeric
    expiration_time_in_seconds). It verifies that expire_reservations()
    survives such objects, keeps expiring well-formed reservations around
    them, and applies the age-gated policy to them: skip and WARN while the
    object is younger than the grace period, delete with a WARNING once it is
    older than any reservation could live.

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

    The remaining two tests pin how the sweep rides the sync worker's retry
    loops: a mid-sweep ExpiredToken must reach retry_with_new_client and
    rebuild the client rather than being swallowed per object
    (test_mid_sweep_expired_token_refreshes_credentials_and_completes), and
    iter_reservation_keys() must retry a throttled page fetch and keep
    threading the ContinuationToken
    (test_iter_reservation_keys_retries_on_throttling_first_page).

    The get_object / head_object / create_client replacements those tests
    install are methods on this class with their per-test state bound in
    with functools.partial. The one patched onto Session.create_client - a
    CLASS attribute, looked up through the descriptor protocol - is wrapped
    in a MagicMock because a bare partial there trips Python 3.13's
    FutureWarning about partial becoming a method descriptor; see
    TestS3ReservationsReader for the same treatment.
    """

    def _put_json_object(self, key: str, payload: Any) -> None:
        """
        Place an arbitrary JSON body directly into the fake bucket,
        bypassing the writer. This models the real-world source of
        malformed objects: content already in the bucket that the
        CURRENT writer did not produce (older schema versions, other
        tooling, since-fixed bugs).

        :param key: The S3 object key to store the body under
        :param payload: Any JSON-serializable value to store as the object body
        """
        self.fake_s3.objects[key] = json.dumps(payload).encode("utf-8")

    def _put_reservation_object(self, reservation_id: str, expires_in_seconds: float) -> str:
        """
        Place a well-formed reservation object (matching the writer's
        on-disk schema) directly into the fake bucket.

        :param reservation_id: The reservation id, which also names the object
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

    def test_control_expired_reservation_is_deleted(self) -> None:
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

    def test_young_wrong_shape_object_is_not_deleted(self) -> None:
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

    def test_old_wrong_shape_object_is_deleted(self) -> None:
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

    def test_object_deleted_mid_check_counts_as_expired(self) -> None:
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

        # Inject onto the in-memory FakeS3Client for the duration of this
        # test only (instance attribute shadows the class method).
        self.fake_s3.head_object = self._head_object_racing_delete

        expired: bool = self.storage.expiration.expire_one_reservation(
            racing_key, time.time(), sync_aws_client=self.fake_s3)

        self.assertTrue(
            expired,
            "Expected a 404 from the head_object age check to be treated as "
            "'already removed by another process' (a successful expiration "
            "outcome), not logged as an S3 error.",
        )

    @staticmethod
    def _head_object_racing_delete(*_args: Any, **_kwargs: Any) -> NoReturn:
        """
        head_object replacement for test_object_deleted_mid_check_counts_as_expired:
        simulates the concurrent deletion by reporting that the object vanished just
        before the HEAD landed, exactly as real S3 would report it.

        :param _args: Positional head_object arguments, ignored
        :param _kwargs: Keyword head_object arguments (Bucket, Key), ignored
        :raises ClientError: a bare "404" HeadObject error, on every call
        """
        raise ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}},
            "HeadObject",
        )

    def test_null_expiration_time_is_treated_as_malformed(self) -> None:
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

    def test_null_reservation_object_does_not_kill_sweep(self) -> None:
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

    def _put_expired_reservation(self, reservation_id: str) -> str:
        """
        Place a well-formed, already-expired reservation object directly
        into the fake bucket (bypassing the writer, as if written by an
        earlier process whose lease has since lapsed).

        :param reservation_id: The reservation id, which also names the object
        :return: the S3 object key used
        """
        key: str = f"reservations/{reservation_id}.json"
        self.fake_s3.objects[key] = json.dumps({
            "name": reservation_id,
            "metadata": {
                "reservation": {
                    "id": reservation_id,
                    "lifetime_in_seconds": 3600.0,
                    # One hour in the past: unambiguously expired.
                    "expiration_time_in_seconds": time.time() - 3600.0,
                },
                "stored_at": time.time() - 7200.0,
            },
        }).encode("utf-8")
        return key

    def test_mid_sweep_expired_token_refreshes_credentials_and_completes(self) -> None:
        """
        Scenario: the sweep's client was built from a token that S3
        rejects by the time the per-object get_object calls run.

        Pins the expiration sweep's recovery from AWS credentials expiring
        MID-sweep - after the listing succeeded but before the per-object
        get/delete calls complete - so that the sweep refreshes credentials
        (by building a new client) and still expires every expired
        reservation, rather than reporting success while doing nothing.

        When this can happen: AwsSyncClientWorker's long-lived client is
        keyless, so token-based credentials (IAM Instance Roles, ECS Task
        Roles, SSO) refresh at signing time and cannot expire mid-sweep. What
        CAN still be rejected mid-sweep are STATIC credentials rotated
        externally - env vars or a credentials file rewritten by another
        process - which botocore resolves once per Session and never re-reads
        on its own. The only recovery mechanism for those is reactive:
        retry_with_new_client() wraps the whole sweep, and when an ExpiredToken
        ClientError reaches it, it discards the session + client and re-runs
        the sweep with a freshly resolved credential chain.

        The failure mode this test guards against: if ExpiredToken errors
        raised by the per-object get_object calls are caught by
        expire_one_reservation's broad except-ClientError handler and merely
        logged, the wrapper never sees them, so credentials are never
        refreshed, every remaining key in the sweep makes exactly one doomed
        S3 call, NOTHING is expired, and expire_reservations() returns as if
        it succeeded. Expired reservations silently linger until a later
        sweep's list_objects_v2 call happens to fail outside the swallowing
        handler.

        Simulation:
          * get_object raises ClientError(ExpiredToken) while the
            token_state flag is set (it starts True).
          * Session.create_client is re-patched so that the SECOND
            client built under this test's patch "refreshes" the token
            (flips the flag) - modeling production, where
            retry_with_new_client discards the session + client and the
            re-resolved credential chain hands back a fresh token.

        Expected: the ExpiredToken propagates out of the per-object
        handling to retry_with_new_client, which rebuilds the client and
        re-runs the sweep; every expired reservation is deleted.

        If expire_one_reservation swallows the ExpiredToken per key
        instead of re-raising it, both assertions fail: the client is
        never rebuilt and all three expired objects remain while the
        sweep reports success.
        """
        expired_keys: List[str] = []
        for index in range(3):
            expired_keys.append(self._put_expired_reservation(f"copy_cat-expired-{index}"))

        # --- simulate a token that has expired for the first client -------
        # Mutable holder shared by the two replacement methods below (bound
        # in through their partials) so that building the second client can
        # flip the flag the get_object replacement checks.
        token_state = {"expired": True}
        real_get_object = self.fake_s3.get_object

        # Inject onto the in-memory FakeS3Client for the duration of this
        # test only (instance attribute shadows the class method).
        self.fake_s3.get_object = partial(self._get_object_with_expiring_token, token_state, real_get_object)

        # --- building a second client models the credential refresh -------
        create_client_calls = {"count": 0}
        # See the class docstring for why the partial is wrapped in a MagicMock
        # rather than patched onto Session.create_client bare.
        create_client = MagicMock(
            side_effect=partial(self._create_client_with_refresh, create_client_calls, token_state))

        # Overrides (stacks on top of) the base class's Session.create_client
        # patch for the duration of this with-block.
        #
        # sync_sleep is patched defensively: ExpiredToken is not in
        # S3Util.is_retryable_client_error's retryable set today, so
        # do_with_retries should not back off on it - but if a regression
        # ever makes it retryable, this keeps the test from sleeping
        # through 8 exponential-backoff retries per object.
        with patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_sync_client_worker.Session.create_client",
            new=create_client,
        ), patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_sync_client_worker.sync_sleep"
        ):
            self.storage.expiration.expire_reservations()

        remaining: List[str] = []
        for key in expired_keys:
            if key in self.fake_s3.objects:
                remaining.append(key)
        self.assertEqual(
            [], remaining,
            f"Expected every expired reservation to be deleted after the credential "
            f"refresh; these remain: {remaining}. This means the mid-sweep "
            f"ExpiredToken was swallowed per-object and never reached "
            f"retry_with_new_client, so the sweep 'succeeded' without expiring "
            f"anything.",
        )
        self.assertGreaterEqual(
            create_client_calls["count"], 2,
            f"Expected at least 2 client constructions under this test's patch "
            f"(rebuilds forced by ExpiredToken reaching retry_with_new_client; the "
            f"second rebuild picks up the fresh token); got "
            f"{create_client_calls['count']}. Fewer means the ExpiredToken never "
            f"triggered retry_with_new_client's session + client reset.",
        )

    def _get_object_with_expiring_token(self, token_state: Dict[str, bool],
                                        real_get_object: Callable[..., Dict[str, Any]],
                                        *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """
        get_object replacement for test_mid_sweep_expired_token_refreshes_credentials_and_completes:
        raises ExpiredToken exactly as boto3 surfaces it (HTTP 400) while the shared
        token_state flag says the token has expired, and delegates to the fake once
        the second client construction has cleared the flag.

        :param token_state: Shared dict whose "expired" entry says whether the current
                client's token is still rejected by S3
        :param real_get_object: The FakeS3Client.get_object this replacement shadows
        :param args: Positional get_object arguments, forwarded to real_get_object unchanged
        :param kwargs: Keyword get_object arguments (Bucket, Key), forwarded unchanged
        :return: real_get_object's response once the token has been refreshed
        :raises ClientError: ExpiredToken while token_state["expired"] is True
        """
        if token_state["expired"]:
            raise self.make_expired_token_error("GetObject")
        return real_get_object(*args, **kwargs)

    def _create_client_with_refresh(self, create_client_calls: Dict[str, int], token_state: Dict[str, bool],
                                    *_args: Any, **_kwargs: Any) -> FakeS3Client:
        """
        Session.create_client replacement for
        test_mid_sweep_expired_token_refreshes_credentials_and_completes: counts client
        constructions and, from the second one on, models the credential refresh by
        clearing the shared token_state flag.

        :param create_client_calls: Shared counter dict; its "count" entry is incremented per call
        :param token_state: Shared dict whose "expired" entry is cleared on the second construction
        :param _args: Positional create_client arguments, ignored
        :param _kwargs: Keyword create_client arguments, ignored
        :return: The in-memory FakeS3Client the base class built in setUp
        """
        create_client_calls["count"] += 1
        if create_client_calls["count"] >= 2:
            # The second re-resolution of the credential chain (via
            # retry_with_new_client discarding the session + client)
            # hands back a fresh token that works from here on.
            token_state["expired"] = False
        return self.fake_s3

    def test_iter_reservation_keys_retries_on_throttling_first_page(self) -> None:
        """
        On a transient ThrottlingException raised by the first
        list_objects_v2 call, iter_reservation_keys() should retry. The
        retry should succeed and pagination should continue using the
        NextContinuationToken returned by the page-1 response. All
        configured keys should be yielded in page order, with no keys
        lost from the failed first attempt.

        S3ReservationsExpiration.iter_reservation_keys() pages through S3 by
        calling list_objects_v2 directly with ContinuationToken, with each
        call wrapped in the sync worker's do_with_retries. This exercises that
        retry behavior: a transient ThrottlingException on the first page-fetch
        attempt is retried, the retry succeeds, pagination continues, and the
        listing yields every key in order - so iter_reservation_keys() recovers
        from a transient ClientError raised by list_objects_v2 and correctly
        threads the ContinuationToken across multiple pages.
        """
        # Two-page listing. Page 1 reports IsTruncated=True with a
        # NextContinuationToken; page 2 reports IsTruncated=False and so
        # ends the loop.
        page_one_response = {
            "Contents": [
                {"Key": "reservations/copy_cat-test-UUID-0001.json"},
                {"Key": "reservations/copy_cat-test-UUID-0002.json"},
            ],
            "IsTruncated": True,
            "NextContinuationToken": "page-2-token",
        }
        page_two_response = {
            "Contents": [
                {"Key": "reservations/copy_cat-test-UUID-0003.json"},
            ],
            "IsTruncated": False,
        }
        throttle_error = ClientError(
            {
                "Error": {"Code": "ThrottlingException"},
                "ResponseMetadata": {"HTTPStatusCode": 503},
            },
            "ListObjectsV2",
        )

        # The side_effect sequence drives the in-order call semantics:
        # call 1 raises (the throttle), call 2 returns page 1 (the retry),
        # call 3 returns page 2. MagicMock raises StopIteration if the
        # production code calls more times than expected, which surfaces
        # over-retry regressions as a hard test failure.
        list_objects_v2 = MagicMock(
            side_effect=[throttle_error, page_one_response, page_two_response]
        )

        # Inject onto the in-memory FakeS3Client for the duration of this
        # test only (instance attribute shadows the class method): the fake's
        # own list_objects_v2 always answers in one page, so the scripted
        # two-page sequence above replaces it here.
        self.fake_s3.list_objects_v2 = list_objects_v2

        # Skip the real exponential-backoff sleep so the test stays fast.
        # Patches the module-local time.sleep symbol that do_with_retries
        # uses.
        with patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_sync_client_worker.sync_sleep"
        ):
            keys = list(self.storage.expiration.iter_reservation_keys(self.fake_s3))

        # Every configured key is yielded exactly once, in page order.
        # Under the original (paginator-based) implementation a mid-listing
        # throttle aborted the whole listing; the rewrite isolates the
        # retry to one page fetch at a time.
        self.assertEqual(
            [
                "reservations/copy_cat-test-UUID-0001.json",
                "reservations/copy_cat-test-UUID-0002.json",
                "reservations/copy_cat-test-UUID-0003.json",
            ],
            keys,
            f"Expected all configured page keys to be yielded after retry; got {keys}.",
        )

        # list_objects_v2 was invoked exactly three times: 1 throttled,
        # 1 retry that returned page 1, 1 that returned page 2. Catches
        # "no retry happened" (count == 1, throttle propagated out) and
        # "over-retried beyond what we expect" (count > 3).
        self.assertEqual(
            3,
            list_objects_v2.call_count,
            f"Expected exactly 3 list_objects_v2 calls (1 throttled + 1 retry + "
            f"1 second page); got {list_objects_v2.call_count}.",
        )

        # The first two calls (page 1 attempt + its retry) carry no
        # ContinuationToken; the third call carries the token returned in
        # page 1's response. Verifies that the production code (a) does
        # not advance the token until the page fetch actually succeeds,
        # and (b) threads the token from one response into the next request.
        actual_tokens: List[Optional[str]] = []
        for call in list_objects_v2.call_args_list:
            actual_tokens.append(call.kwargs.get("ContinuationToken"))
        self.assertEqual(
            [None, None, "page-2-token"],
            actual_tokens,
            f"Expected ContinuationToken sequence [None, None, 'page-2-token']; "
            f"got {actual_tokens}.",
        )
