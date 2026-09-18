
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
from functools import partial
from json import loads

from typing import Any
from typing import Callable
from typing import Dict
from typing import NoReturn

from unittest.mock import patch

from aiobotocore.session import AioSession
from aiobotocore.session import get_session as real_get_session
from botocore.exceptions import ClientError
from botocore.exceptions import NoCredentialsError
from jsonschema import validate

from neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage import S3ReservationsStorage
from neuro_san.service.watcher.temp_networks.s3.s3_util import S3Util

from tests.neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


class TestS3ReservationsWriter(S3ReservationsStorageTestBase):
    """
    Unit tests for S3ReservationsWriter, reached through the add_reservations
    facade of the S3ReservationsStorage that S3ReservationsStorageTestBase
    wires to an in-memory fake S3 client (S3ReservationsStorage.add_reservations
    is a one-line delegation to the writer).

    Every test here is write-only: it asserts on what lands in the fake bucket
    (object key layout, JSON body shape, prefix handling, batch semantics) and
    on how the async worker's retry and credential-recovery loops behave around
    put_object. Write-then-read round trips through the facade live in
    test_s3_reservations_storage.py and the read path in
    test_s3_reservations_reader.py.

    Retry policy, pinned across four tests: a transient ThrottlingException is
    retried until the put succeeds (test_add_retries_on_throttling_then_succeeds);
    a permanent AccessDenied is not retried at all
    (test_add_does_not_retry_on_access_denied); and a credential rejection on
    the batch's first session - S3's InvalidToken or a local NoCredentialsError -
    discards the shared AioSession and completes the batch through a re-resolved
    chain (the two *_triggers_session_rebuild_and_batch_succeeds tests). Batch
    semantics are one put_object per entry in a plain for-loop with no atomic
    rollback (test_add_preserves_earlier_successes_when_later_entry_fails).

    The put_object / get_session replacements the tests install are methods on
    this class with their per-test state (call counters, the real put_object
    they shadow) bound in with functools.partial, because the project's style
    forbids nested functions and lambdas.
    """

    # Documents the on-disk JSON shape that the writer commits to. The schema
    # is the single source of truth for the format and is what external
    # consumers (CLI tools, dashboards, debug operators) can rely on. Any
    # future test that needs to pin the same shape can reuse this constant.
    RESERVATION_OBJECT_SCHEMA: Dict[str, Any] = {
        "type": "object",
        "required": ["name", "llm_config", "tools", "metadata"],
        "properties": {
            # Original agent_spec fields are preserved at the top level.
            # The storage does NOT wrap the spec in an outer envelope
            # like {"data": ...}.
            "name": {"type": "string"},
            "llm_config": {"type": "object"},
            "tools": {"type": "array"},
            # Storage-injected bookkeeping fields live under "metadata",
            # side by side with any user-authored metadata fields.
            "metadata": {
                "type": "object",
                "required": ["reservation", "stored_at"],
                "properties": {
                    "reservation": {
                        "type": "object",
                        "required": [
                            "id",
                            "lifetime_in_seconds",
                            "expiration_time_in_seconds",
                        ],
                        "properties": {
                            "id": {"type": "string"},
                            "lifetime_in_seconds": {"type": "number"},
                            "expiration_time_in_seconds": {"type": "number"},
                        },
                    },
                    "stored_at": {"type": "number"},
                },
            },
        },
    }

    async def test_add_writes_at_expected_object_key(self) -> None:
        """
        add_reservations writes each reservation to a specific S3 object key;
        this pins that key format as a contract.

        The S3 object key written by add_reservations follows the documented
        format "{prefix}{reservation_id}.json". A refactor that changes the
        layout (e.g., to "{prefix}{id}/data.json") would still let the
        round-trip test pass because read and write both go through the same
        helper. This test pins the observable contract from the outside by
        asserting against a hardcoded literal path.

        After add_reservations, the S3 bucket contains exactly one object,
        and that object's key matches the documented "{prefix}{id}.json"
        format. The write-side path and the read-side helper agree on the
        same key.
        """
        # New reservation id; -0001 through -0003 are reserved by the
        # round-trip tests.
        reservation_id = "copy_cat-test-UUID-0004"
        reservation = self._make_reservation(reservation_id, lifetime_seconds=600.0)
        agent_spec = self._make_agent_spec("copy_cat")

        # Write
        await self.storage.add_reservations({reservation: agent_spec})

        # Hardcoded literal of the expected path. Constructing this from
        # the storage's own helper would defeat the purpose of pinning
        # the format - a refactored helper would silently match a
        # refactored writer. The prefix "reservations/" is configured in
        # S3ReservationsStorageTestBase.setUp; the per-reservation suffix "{id}.json" is
        # the documented layout.
        expected_key = f"reservations/{reservation_id}.json"

        # Exactly one object exists, at exactly the expected path. This
        # single assertion catches several unrelated bugs:
        #   * wrong prefix (e.g., "reserve_/")
        #   * missing or different suffix (e.g., no ".json", or ".dat")
        #   * extra slash between prefix and id ("reservations//id.json")
        #   * a leaked second blob written under a sibling key
        self.assertEqual(
            [expected_key],
            list(self.fake_s3.objects),
            f"Expected exactly one S3 object at {expected_key!r}, got "
            f"{list(self.fake_s3.objects)}",
        )

        # The read-side helper produces the same key the writer used.
        # Guards against the read and write paths drifting out of sync
        # (e.g., the writer is refactored but the helper is not).
        self.assertEqual(
            expected_key,
            S3Util.get_obj_key_for_reservation(self.storage.writer.prefix, reservation_id),
            "get_obj_key_for_reservation does not produce the same key "
            "the storage wrote to; read and write would disagree.",
        )

    async def test_add_writes_json_body_with_expected_top_level_shape(self) -> None:
        """
        The writer commits to a specific on-disk format for every
        reservation it writes:
          - Serialization is JSON (we chose json.dumps, not pickle/yaml/proto).
          - The original agent_spec lives at the top level of the document
            (no wrap-in-envelope like {"data": ...}).
          - Storage-injected bookkeeping fields live under a "metadata" key
            ("reservation" with the serialized Reservation, "stored_at" with
            the wall-clock timestamp).

        External consumers (CLI tools, dashboards, debugging operators) read
        these objects directly and rely on the format being stable. The
        round-trip test in test_s3_reservations_storage.py would still pass
        if the read+write paths were updated together but the on-disk format
        silently changed; this test pins the format by reading the raw bytes
        and validating the parsed document against a JSON Schema, independent
        of the storage's read path.

        Encoding/line-ending properties (UTF-8, no BOM, no CRLF) are
        boto3+Python concerns and are intentionally NOT tested here.

        After add_reservations, the S3 object body should:
          - Decode as a JSON object (we chose JSON over
            pickle/yaml/proto).
          - Match RESERVATION_OBJECT_SCHEMA: original agent_spec
            fields at the top level (no wrap-in-envelope), with
            storage-injected reservation+stored_at under
            "metadata".

        Catches regressions in our serialization choice: a switch
        to a different format, an outer envelope refactor, dropped
        or relocated metadata fields, or a wrong reservation id
        under metadata.
        """
        reservation_id = "copy_cat-test-UUID-0012"
        reservation = self._make_reservation(reservation_id, lifetime_seconds=600.0)
        agent_spec = self._make_agent_spec("copy_cat")

        await self.storage.add_reservations({reservation: agent_spec})

        # The object must exist at the expected key (sanity guard;
        # the format assertions below would surface as a confusing
        # KeyError otherwise).
        expected_key = f"reservations/{reservation_id}.json"
        self.assertIn(
            expected_key,
            self.fake_s3.objects,
            f"Expected object at {expected_key!r}; bucket has "
            f"{list(self.fake_s3.objects)}.",
        )
        body: bytes = self.fake_s3.objects[expected_key]

        # Parse the raw bytes as JSON. Catches a switch in our
        # serialization choice (pickle, yaml, protobuf) - all of
        # which would either raise or yield a non-dict here.
        parsed = loads(body)

        # Single declarative shape assertion against the documented
        # schema. Catches wrap-in-envelope refactors, dropped or
        # relocated metadata fields, renamed top-level keys, and
        # mistyped values (e.g., reservation.id stored as a number).
        # jsonschema raises ValidationError on mismatch, which
        # pytest surfaces with a JSONPath pointing at the offending
        # node.
        validate(instance=parsed, schema=self.RESERVATION_OBJECT_SCHEMA)

        # Schema validates shape; this assert pins value correctness:
        # the reservation id we wrote is the id stored under
        # metadata.reservation.id. Catches a regression where the
        # storage writes a placeholder or the wrong id while still
        # producing a schema-valid document.
        self.assertEqual(
            reservation_id,
            parsed["metadata"]["reservation"]["id"],
            f"Reservation id under metadata.reservation.id did not "
            f"match the id we wrote; expected {reservation_id!r}, "
            f"got {parsed['metadata']['reservation'].get('id')!r}.",
        )

    async def test_add_uses_configured_prefix_for_object_keys(self) -> None:
        """
        S3ReservationsStorage accepts a configurable prefix (default
        "reservations/") that's prepended to every reservation's S3 object
        key. Production deploys may set a non-default prefix for
        multi-tenancy, environment separation (prod/staging), or version
        migration. This verifies that add_reservations writes objects
        under the configured prefix - catching regressions where the prefix
        is hardcoded or otherwise dropped.

        The other tests in this suite all use the default prefix
        "reservations/". None of them detect a hardcoded-prefix regression
        in get_obj_key_for_reservation, because the hardcoded value matches
        the default by coincidence. This test exercises a non-default
        prefix to surface that class of bug.

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

    async def test_add_with_empty_dict_is_a_no_op(self) -> None:
        """
        add_reservations should be a complete no-op when called with an
        empty mapping. Real callers may legitimately pass {} when
        pre-filtering yields no new reservations; the storage must handle
        that without crashing, without writing placeholder objects, and
        without making any S3 calls.

        The empty-batch contract: add_reservations({}) is equivalent to
        not calling add_reservations at all. No exception, no S3 call, no
        bucket mutation. The other tests in this suite all use N>=1
        entries, so none of them touch this path.

        add_reservations({}) returns normally, makes zero put_object
        calls, and leaves the bucket exactly as it was. Catches
        regressions where empty input crashes (KeyError, IndexError,
        StopIteration) or silently writes placeholder entries.
        """
        # Wrap put_object so we can count attempts. Real put still
        # works for any incidental call (which there should be zero of).
        real_put = self.fake_s3.put_object
        call_log = {"count": 0}
        self.fake_s3.put_object = partial(self._counting_put, call_log, real_put)

        # The bucket starts empty; record that as the precondition we
        # expect to remain unchanged.
        self.assertEqual(
            0,
            len(self.fake_s3.objects),
            "Precondition violated: bucket should start empty.",
        )

        # The call should return normally - no exception. If this
        # raises, the no-op contract is broken and the call site needs
        # defensive guards it should not need.
        await self.storage.add_reservations({})

        # No put_object call was made. Catches a regression where the
        # storage attempts to write a placeholder for an empty input,
        # or where empty-input handling falls through into the loop
        # body with sentinel data.
        self.assertEqual(
            0,
            call_log["count"],
            f"Expected zero put_object calls for empty input; got "
            f"{call_log['count']}. The storage is making S3 traffic "
            f"for an empty batch.",
        )

        # The bucket is still empty - end-to-end check that no S3
        # mutation occurred. Redundant with the call-count check above
        # but reads as the user-facing contract on its own.
        self.assertEqual(
            0,
            len(self.fake_s3.objects),
            f"Expected empty bucket after empty-input call; bucket has "
            f"{list(self.fake_s3.objects)}.",
        )

    @staticmethod
    def _counting_put(call_log: Dict[str, int], real_put: Callable[..., Dict[str, Any]],
                      *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """
        put_object replacement for test_add_with_empty_dict_is_a_no_op: counts
        every attempt and lets each one fall through to the real in-memory store.

        :param call_log: Shared counter dict; its "count" entry is incremented per call
        :param real_put: The FakeS3Client.put_object this replacement shadows
        :param args: Positional put_object arguments, forwarded to real_put unchanged
        :param kwargs: Keyword put_object arguments (Bucket, Key, Body, ContentType),
                forwarded to real_put unchanged
        :return: real_put's response
        """
        call_log["count"] += 1
        return real_put(*args, **kwargs)

    async def test_add_preserves_earlier_successes_when_later_entry_fails(self) -> None:
        """
        add_reservations writes batch entries one at a time in a Python
        for-loop with no atomic-batch semantics. This exercises the
        partial-failure case: if a later entry's put_object fails, earlier
        successful writes remain in S3 (no automatic rollback).

        Pins the current partial-success contract of add_reservations:
        earlier iterations of the for-loop are NOT rolled back when a later
        iteration raises. A future change that introduces atomic-batch
        semantics (rollback on failure) would intentionally break this test
        and require an explicit update, surfacing the contract change in
        code review rather than letting it slip in silently.

        With a batch of 3 reservations where the 3rd put_object raises
        AccessDenied, add_reservations propagates the error and leaves
        the 1st and 2nd writes intact in S3. The 3rd entry's key is not
        in S3 (its put failed before any S3 mutation).
        """
        # Three reservation ids; iteration order matches insertion order
        # in the dict literal below (Python 3.7+ guaranteed).
        res_a = self._make_reservation("copy_cat-test-UUID-0008a", lifetime_seconds=600.0)
        res_b = self._make_reservation("copy_cat-test-UUID-0008b", lifetime_seconds=1200.0)
        res_c = self._make_reservation("copy_cat-test-UUID-0008c", lifetime_seconds=1800.0)

        # Distinct model_names per spec - if a future bug merges specs
        # across iterations, the surviving objects would carry the wrong
        # model_name and a follow-up read could surface that.
        spec_a = self._make_agent_spec("copy_cat")
        spec_a["llm_config"]["model_name"] = "gpt-4o"
        spec_b = self._make_agent_spec("copy_cat")
        spec_b["llm_config"]["model_name"] = "claude-3-5-sonnet"
        spec_c = self._make_agent_spec("copy_cat")
        spec_c["llm_config"]["model_name"] = "gemini-2.0-flash"

        # Wrap put_object: only the 3rd call raises AccessDenied;
        # iterations 1 and 2 fall through to the real in-memory store.
        # Status 403 lands the error on the non-retryable branch of
        # S3Util.is_retryable_client_error so we know the failure is final.
        real_put = self.fake_s3.put_object
        # Defensively restore put_object on the fake at end-of-test. The
        # base class hands each test a fresh FakeS3Client in setUp, so
        # this is a no-op today; the cleanup is here to document intent
        # and to keep the test correct if a future refactor turns
        # self.fake_async_s3 into a shared object.
        self.addCleanup(setattr, self.fake_s3, "put_object", real_put)
        call_log = {"count": 0}
        template_error = ClientError(
            {
                "Error": {"Code": "AccessDenied"},
                "ResponseMetadata": {"HTTPStatusCode": 403},
            },
            "PutObject",
        )
        self.fake_s3.put_object = partial(self._put_object_failing_on_third, call_log, template_error, real_put)

        # Skip backoff sleep defensively. AccessDenied is non-retryable
        # so no sleep should fire, but we patch it so a regression that
        # adds AccessDenied to retryable_codes does not hang the test.
        with patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_async_client_worker.async_sleep"
        ):

            with self.assertRaises(ClientError) as ctx:
                await self.storage.add_reservations(
                    {res_a: spec_a, res_b: spec_b, res_c: spec_c}
                )

        # The original AccessDenied error code propagates. Catches a
        # bug where the storage swallows the error or wraps it in a
        # different exception type.
        self.assertEqual(
            "AccessDenied",
            ctx.exception.response["Error"]["Code"],
            "AccessDenied error code was not preserved on propagation.",
        )

        # Exactly 3 put attempts: 2 successful, 1 that failed. Catches
        # bugs where the loop continues past the failure (count > 3) or
        # stops early before the third entry (count < 3).
        self.assertEqual(
            3,
            call_log["count"],
            f"Expected exactly 3 put_object attempts (2 succeeded + 1 "
            f"failed); got {call_log['count']}.",
        )

        # The two earlier successes survive in S3. Catches:
        # - rollback regression: bucket would be empty
        # - leaked third write: bucket would contain res_c's key
        # - cross-contamination: extra/wrong keys present
        expected_surviving = {
            f"reservations/{res_a.get_reservation_id()}.json",
            f"reservations/{res_b.get_reservation_id()}.json",
        }
        self.assertEqual(
            expected_surviving,
            set(self.fake_s3.objects),
            f"Expected the two earlier successes to survive in S3, got "
            f"{list(self.fake_s3.objects)}. The storage is rolling back "
            f"earlier writes or leaking the failed write.",
        )

        # Belt-and-suspenders: the failed entry's key is NOT in S3.
        # Redundant with the set assertion above but reads as the
        # intended contract on its own and gives a clear failure
        # message if a partial write leaks just the failed key.
        self.assertNotIn(
            f"reservations/{res_c.get_reservation_id()}.json",
            self.fake_s3.objects,
            f"Failed entry's key leaked into S3; bucket has "
            f"{list(self.fake_s3.objects)}.",
        )

    @staticmethod
    def _put_object_failing_on_third(call_log: Dict[str, int], template_error: ClientError,
                                     real_put: Callable[..., Dict[str, Any]],
                                     *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """
        put_object replacement for test_add_preserves_earlier_successes_when_later_entry_fails:
        counts every attempt and raises template_error on exactly the third one,
        letting every other call fall through to the real in-memory store.

        :param call_log: Shared counter dict; its "count" entry is incremented per call
        :param template_error: The ClientError to raise on the third attempt
        :param real_put: The FakeS3Client.put_object this replacement shadows
        :param args: Positional put_object arguments, forwarded to real_put unchanged
        :param kwargs: Keyword put_object arguments (Bucket, Key, Body, ContentType),
                forwarded to real_put unchanged
        :return: real_put's response for the calls that are allowed through
        :raises ClientError: template_error, on the third call only
        """
        call_log["count"] += 1
        if call_log["count"] == 3:
            raise template_error

        return real_put(*args, **kwargs)

    async def test_add_retries_on_throttling_then_succeeds(self) -> None:
        """
        The writer routes every put_object call through the async worker's
        do_with_retries. This exercises the happy retry path: a transient
        ThrottlingException on the first attempt is retried, the retry
        succeeds, and S3 ends up consistent.

        The other tests in this suite run against a FakeS3Client that never
        fails, so they never reach the retry branch of do_with_retries. This
        test fills that gap by injecting a one-shot ThrottlingException on
        the first put_object attempt and verifying the storage retries until
        the put succeeds.

        On a transient ThrottlingException, add_reservations should
        retry the put_object call. The retry should succeed and S3
        should contain exactly one object at the documented key, with
        no duplicate writes leaked from the failed first attempt.
        """
        reservation_id = "copy_cat-test-UUID-0006"
        reservation = self._make_reservation(reservation_id, lifetime_seconds=600.0)
        agent_spec = self._make_agent_spec("copy_cat")

        # Wrap put_object so the FIRST call raises a retryable
        # ThrottlingException, and every subsequent call falls through
        # to the real in-memory store.
        real_put = self.fake_s3.put_object
        call_log = {"count": 0}
        self.fake_s3.put_object = partial(self._throttle_first_put, call_log, real_put)

        # Skip the real exponential-backoff sleep so the test stays
        # fast. Patches the module-local asyncio.sleep symbol that
        # do_with_retries uses.
        with patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_async_client_worker.async_sleep"
        ):
            await self.storage.add_reservations({reservation: agent_spec})

        # put_object was invoked exactly twice: once that threw, once
        # that succeeded. Catches "no retry happened" (count == 1) and
        # "over-retried beyond what we expect" (count > 2).
        self.assertEqual(
            2,
            call_log["count"],
            f"Expected exactly 2 put_object attempts (1 throttled + "
            f"1 retry that succeeded); got {call_log['count']}.",
        )

        # Exactly one S3 object survives. Catches a leaked duplicate
        # from the throttled attempt or the retry.
        self.assertEqual(
            1,
            len(self.fake_s3.objects),
            f"Expected exactly one S3 object after retry; bucket has "
            f"{list(self.fake_s3.objects)}.",
        )

        # That one object is at the documented key (prefix + id +
        # ".json"). Final round-trip-style sanity check.
        expected_key = f"reservations/{reservation_id}.json"
        self.assertIn(
            expected_key,
            self.fake_s3.objects,
            f"Expected S3 object at {expected_key!r}, found "
            f"{list(self.fake_s3.objects)}.",
        )

    @staticmethod
    def _throttle_first_put(call_log: Dict[str, int], real_put: Callable[..., Dict[str, Any]],
                            *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """
        put_object replacement for test_add_retries_on_throttling_then_succeeds:
        the FIRST call raises a retryable ThrottlingException (HTTP 503) and every
        subsequent call falls through to the real in-memory store.

        :param call_log: Shared counter dict; its "count" entry is incremented per call
        :param real_put: The FakeS3Client.put_object this replacement shadows
        :param args: Positional put_object arguments, forwarded to real_put unchanged
        :param kwargs: Keyword put_object arguments (Bucket, Key, Body, ContentType),
                forwarded to real_put unchanged
        :return: real_put's response for every call after the first
        :raises ClientError: ThrottlingException, on the first call only
        """
        call_log["count"] += 1
        if call_log["count"] == 1:
            raise ClientError(
                {
                    "Error": {"Code": "ThrottlingException"},
                    "ResponseMetadata": {"HTTPStatusCode": 503},
                },
                "PutObject",
            )
        return real_put(*args, **kwargs)

    async def test_add_does_not_retry_on_access_denied(self) -> None:
        """
        S3Util.is_retryable_client_error classifies errors into retryable
        (transient: throttling, slow-down, 5xx) and non-retryable (permanent:
        AccessDenied, malformed request, etc.). This exercises the
        non-retryable branch: an AccessDenied ClientError must propagate
        immediately, with no S3 mutation and nothing retrievable through
        the public read path.

        Companion to test_add_retries_on_throttling_then_succeeds, which
        pinned that transient errors DO retry; this test pins that
        AccessDenied does NOT retry. Together they document the storage's
        full retry policy.

        On AccessDenied (HTTP 403 with error code AccessDenied -
        what real S3 returns for permission errors), add_reservations
        should propagate the error immediately without any retry, and
        leave nothing in S3 nor anything retrievable through the public
        read path.
        """
        reservation_id = "copy_cat-test-UUID-0007"
        reservation = self._make_reservation(reservation_id, lifetime_seconds=600.0)
        agent_spec = self._make_agent_spec("copy_cat")

        # Wrap put_object: every call raises AccessDenied. Status 403
        # is what real S3 returns for permission errors and lands the
        # error on the non-retryable branch of is_retryable_client_error
        # (AccessDenied is not in retryable_codes; 403 is not 5xx).
        call_log = {"count": 0}

        template_error = ClientError(
            {
                "Error": {"Code": "AccessDenied"},
                "ResponseMetadata": {"HTTPStatusCode": 403},
            },
            "PutObject",
        )
        self.fake_async_s3.put_object = partial(self._denied_put, call_log, template_error)

        # Skip backoff sleep defensively. If a regression makes
        # AccessDenied retryable, we don't want the test to hang.
        with patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_async_client_worker.async_sleep"
        ):
            with self.assertRaises(ClientError) as ctx:
                await self.storage.add_reservations({reservation: agent_spec})

        # The original error code is preserved on the way up. Catches
        # bugs where the storage swallows or wraps the error in a
        # different exception type, hiding the real cause from callers.
        self.assertEqual(
            "AccessDenied",
            ctx.exception.response["Error"]["Code"],
            "AccessDenied error code was not preserved on propagation; "
            "the original cause is being hidden from callers.",
        )

        # Exactly ONE put_object attempt - no retries fired on a
        # non-retryable error. Catches a regression where AccessDenied
        # is added to retryable_codes (would cost N attempts and N
        # backoff sleeps before the error finally surfaces).
        self.assertEqual(
            1,
            call_log["count"],
            f"Expected exactly 1 put_object attempt for non-retryable "
            f"AccessDenied; got {call_log['count']}. The storage is "
            f"retrying a non-retryable error.",
        )

        # No S3 object was written. Catches a regression where the
        # storage somehow puts a partial object before the error
        # propagates up.
        self.assertEqual(
            0,
            len(self.fake_s3.objects),
            f"Expected empty bucket after AccessDenied; bucket has "
            f"{list(self.fake_s3.objects)}.",
        )

        # The failed reservation is NOT retrievable through the public
        # read path. Confirms end-to-end that nothing leaked into any
        # cache or fallback store: a fresh caller asking for this id
        # gets None, as if the failed write had never happened.
        result_reservation, result_network = \
            self.storage.get_one_reservation(reservation_id)
        self.assertIsNone(
            result_reservation,
            f"get_one_reservation returned a Reservation for "
            f"{reservation_id!r} after AccessDenied; the failed write "
            f"should leave nothing retrievable.",
        )
        self.assertIsNone(
            result_network,
            f"get_one_reservation returned an AgentNetwork for "
            f"{reservation_id!r} after AccessDenied; the failed write "
            f"should leave nothing retrievable.",
        )

    @staticmethod
    def _denied_put(call_log: Dict[str, int], template_error: ClientError,
                    *_args: Any, **_kwargs: Any) -> NoReturn:
        """
        put_object replacement for test_add_does_not_retry_on_access_denied:
        counts the attempt and raises template_error every time.

        :param call_log: Shared counter dict; its "count" entry is incremented per call
        :param template_error: The AccessDenied ClientError to raise on every call
        :param _args: Positional put_object arguments, ignored
        :param _kwargs: Keyword put_object arguments, ignored
        :raises ClientError: template_error, on every call
        """
        call_log["count"] += 1
        raise template_error

    async def _run_batch_with_bad_first_session(self, make_error: Callable[[], Exception]) -> Dict[str, int]:
        """
        Drive one add_reservations batch where every put_object made
        under the FIRST session's credential state raises make_error(),
        and the state heals once the retry has built a SECOND session
        (modeling a rotation that lands between the two resolutions).

        Pins credential recovery on the reservation WRITE path: a deployment
        batch whose first attempt fails against a bad credential state must
        discard the shared AioSession, re-resolve the chain behind a fresh
        session, retry, and land the write - not lose the batch.

        A lost batch is the worst credential failure mode this storage has:
        add_reservations raises, the updater logs and drops the item (there is
        no requeue), and other pods then report the just-created network
        not-found. Covered by the two callers for both faces of a rotation
        window:

          * InvalidToken - S3 rejects the request the batch's client signed
            with a bad resolved credential state (a ClientError; the same
            production failure the reader-path test in
            test_s3_reservations_reader.py pins, see neuro-san-studio #1310).
          * NoCredentialsError - the chain behind the batch's fresh client
            resolved to nothing (credentials file caught empty mid-rewrite),
            raised locally by botocore at request-signing time. This is a
            BotoCoreError, NOT a ClientError: under a ClientError-only retry
            gate it escapes with retry budget unused and the batch is lost -
            the recovery test fails exactly that way against such a gate.

        :param make_error: Zero-arg factory for the exception each
                doomed put_object raises.
        :return: Counters: sessions created and put_object attempts.
        """
        reservation = self._make_reservation("copy_cat-test-UUID-cred-rec", lifetime_seconds=600.0)
        spec: Dict[str, Any] = self._make_agent_spec("copy_cat")

        counters = {"sessions": 0, "puts": 0}

        real_put = self.fake_s3.put_object
        self.fake_s3.put_object = partial(self._put_object_bad_until_second_session, counters, make_error, real_put)
        self.addCleanup(setattr, self.fake_s3, "put_object", real_put)

        # get_session is a module-level name in aws_async_client_worker, so a
        # bare partial can stand in for it. async_sleep is patched so the
        # credential retry's jittered backoff does not slow the test down;
        # recovery is unaffected.
        with patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_async_client_worker.get_session",
            new=partial(self._counting_get_session, counters),
        ), patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_async_client_worker.async_sleep"
        ):
            await self.storage.add_reservations({reservation: spec})

        obj_key: str = S3Util.get_obj_key_for_reservation(
            self.PREFIX, reservation.get_reservation_id())
        self.assertIn(
            obj_key, self.fake_s3.objects,
            f"Expected the batch to land in S3 after the credential retry "
            f"rebuilt the session; bucket has {list(self.fake_s3.objects)}. "
            f"A missing key means the batch was lost - other pods would "
            f"report the just-created network not-found.",
        )
        self.assertGreaterEqual(
            counters["sessions"], 2,
            f"Expected at least 2 session creations (the one with the bad "
            f"credential state plus the retry's rebuild); got "
            f"{counters['sessions']}. A single session means the credential "
            f"retry never discarded it.",
        )
        return counters

    @staticmethod
    def _counting_get_session(counters: Dict[str, int], *args: Any, **kwargs: Any) -> AioSession:
        """
        get_session replacement for _run_batch_with_bad_first_session: counts how
        many AioSessions the async worker builds, then builds a real one.

        :param counters: Shared counter dict; its "sessions" entry is incremented per call
        :param args: Positional get_session arguments, forwarded unchanged
        :param kwargs: Keyword get_session arguments, forwarded unchanged
        :return: The real aiobotocore AioSession
        """
        counters["sessions"] += 1
        return real_get_session(*args, **kwargs)

    @staticmethod
    def _put_object_bad_until_second_session(counters: Dict[str, int], make_error: Callable[[], Exception],
                                             real_put: Callable[..., Dict[str, Any]],
                                             *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """
        put_object replacement for _run_batch_with_bad_first_session: every put made
        while fewer than two sessions have been built raises make_error(), modeling
        the first session's bad credential state; once the retry has built a second
        session the put falls through to the real in-memory store.

        :param counters: Shared counter dict; "puts" is incremented per call and
                "sessions" (maintained by _counting_get_session) decides the outcome
        :param make_error: Zero-arg factory for the exception each doomed put raises
        :param real_put: The FakeS3Client.put_object this replacement shadows
        :param args: Positional put_object arguments, forwarded to real_put unchanged
        :param kwargs: Keyword put_object arguments (Bucket, Key, Body, ContentType),
                forwarded to real_put unchanged
        :return: real_put's response once the second session exists
        :raises Exception: whatever make_error() builds, while on the first session
        """
        counters["puts"] += 1
        if counters["sessions"] < 2:
            # Still on the first session's bad credential state.
            raise make_error()
        return real_put(*args, **kwargs)

    async def test_invalid_token_triggers_session_rebuild_and_batch_succeeds(self) -> None:
        """
        S3 rejects the first attempt's request with InvalidToken (HTTP
        400, non-retryable within do_with_retries): the credential gate
        must discard the session and complete the batch on the retry.
        """
        await self._run_batch_with_bad_first_session(self._make_invalid_token)

    @staticmethod
    def _make_invalid_token() -> ClientError:
        """
        Build the ClientError S3 surfaces for a request signed with a malformed
        or mismatched session token (HTTP 400, body code "InvalidToken").

        :return: The InvalidToken ClientError for a PutObject operation
        """
        return ClientError(
            {
                "Error": {
                    "Code": "InvalidToken",
                    "Message": "The provided token is malformed or otherwise invalid.",
                },
                "ResponseMetadata": {"HTTPStatusCode": 400},
            },
            "PutObject",
        )

    async def test_empty_chain_triggers_session_rebuild_and_batch_succeeds(self) -> None:
        """
        The first attempt's put_object raises NoCredentialsError at
        signing time (empty chain behind that session's client).
        do_with_retries deliberately fast-fails it; the credential
        retry must catch it ALONGSIDE ClientError - it is a
        BotoCoreError - discard the session, and complete the batch.
        Under a ClientError-only gate this test fails with the raw
        NoCredentialsError propagating out of add_reservations.
        """
        await self._run_batch_with_bad_first_session(NoCredentialsError)
