
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

from functools import partial

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from unittest.mock import MagicMock
from unittest.mock import patch

from neuro_san.interfaces.reservation import Reservation
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.service.watcher.temp_networks.s3.s3_util import S3Util

from tests.neuro_san.internals.network_providers.byok_agent_spec_builder import ByokAgentSpecBuilder
from tests.neuro_san.service.watcher.temp_networks.s3.fake_s3_client import FakeS3Client
from tests.neuro_san.service.watcher.temp_networks.s3.invalid_token_s3_client import InvalidTokenS3Client
from tests.neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase
from tests.neuro_san.service.watcher.temp_networks.s3.token_bound_s3_client import TokenBoundS3Client


class TestS3ReservationsReader(S3ReservationsStorageTestBase):
    """
    Unit tests for S3ReservationsReader, reached through the reader that
    S3ReservationsStorageTestBase wires to an in-memory fake S3 client.

    Two families of behaviour are pinned here. The first is what the reader
    does with the bytes it fetches: the read path resolves each stored agent
    spec through ResolvedNetworkConfigFilter before building the AgentNetwork.
    ExpiringAgentNetworkStorage already resolves specs before writing them, so
    in steady state that is a no-op; it matters for objects written by older
    instances during a rolling upgrade or by other tooling. Such objects never
    went through the reservationist's validators, so the reader must also
    treat a spec that makes the filter raise as "not present" rather than let
    the exception escape onto the request path, matching LocalReservationsStorage.

    The second is the lifecycle of the S3 client the reader fetches with,
    which runs on the request path: repeated reads must reuse one long-lived
    client (test_repeated_reads_reuse_one_client), that client must be created
    keylessly so botocore refreshes rotated tokens proactively at signing time
    (test_token_rotation_between_reads_causes_no_failed_call), and when the
    credential state is bad anyway - S3 rejecting the token as InvalidToken,
    or the chain resolving to nothing mid-rotation - the sync worker's
    credential retry must rebuild the session + client and complete the read
    instead of reporting the reservation not-found (the two *_recovery tests).
    Those tests reach AwsSyncClientWorker through the reader's entry point and
    the base class's create_client seam.

    The create_client / get_credentials replacements the lifecycle tests
    install are methods on this class. Where they need per-test state the
    state is bound in with functools.partial and the partial is wrapped in a
    MagicMock: Session.create_client and Session.get_credentials are CLASS
    attributes, so the worker's self.session.create_client(...) lookup runs
    the descriptor protocol on whatever is patched in, and a bare partial trips
    Python 3.13's FutureWarning that partial is about to become a method
    descriptor (which would start prepending the Session instance). A MagicMock
    is not a descriptor and forwards the call to its side_effect unchanged -
    the same idiom test_repeated_reads_reuse_one_client already uses on this seam.
    """

    NUM_READS: int = 5

    def _put_raw_byok_reservation(self, reservation_id: str, overrides: Dict[str, Any] = None) -> str:
        """
        Place an unexpired reservation object whose agent spec has NOT been through the
        filter chain directly into the fake bucket, matching the writer's on-disk schema
        but bypassing ExpiringAgentNetworkStorage (which would have resolved it).

        :param reservation_id: The reservation id, which readers turn into the S3 key
        :param overrides: Optional top-level keys to set on the spec before it is stored,
                used to make the spec malformed on purpose. None means store it as built.
        :return: The reservation id
        """
        agent_spec: Dict[str, Any] = ByokAgentSpecBuilder.make_spec(reservation_id)
        if overrides is not None:
            agent_spec.update(overrides)
        agent_spec["metadata"] = {
            "reservation": {
                "id": reservation_id,
                "lifetime_in_seconds": 3600.0,
                "expiration_time_in_seconds": time.time() + 3600.0,
            },
            "stored_at": time.time(),
        }
        key: str = S3Util.get_obj_key_for_reservation(self.PREFIX, reservation_id)
        self.fake_s3.objects[key] = json.dumps(agent_spec).encode("utf-8")
        return reservation_id

    def test_get_one_reservation_resolves_raw_spec(self) -> None:
        """
        Reading a raw spec yields an AgentNetwork whose front man carries the merged
        global sly_data_schema and the network-level llm_config.
        """
        reservation_id: str = self._put_raw_byok_reservation("byok-raw")

        reservation: Optional[Reservation]
        agent_network: Optional[AgentNetwork]
        reservation, agent_network = self.storage.reader.get_one_reservation(reservation_id)

        self.assertIsNotNone(reservation)
        self.assertIsInstance(agent_network, AgentNetwork)
        front_man_spec: Dict[str, Any] = ByokAgentSpecBuilder.front_man_spec(agent_network)
        self.assertEqual(["llm_config"], front_man_spec["function"]["sly_data_schema"]["required"])
        self.assertIn("openai_api_key",
                      front_man_spec["function"]["sly_data_schema"]["properties"]["llm_config"]["properties"])
        self.assertIn("fallbacks", front_man_spec["llm_config"])

    def test_get_one_reservation_strips_legacy_commondefs(self) -> None:
        """
        A raw spec that still carries a commondefs block (older instances stored specs as
        deployed) has the substitution applied and the block dropped, exactly as the write
        side does now, so every instance serves the same network.
        """
        reservation_id: str = self._put_raw_byok_reservation(
            "byok-legacy-commondefs", {"commondefs": {"replacement_strings": {"greet": "hello"}}})
        spec_key: str = S3Util.get_obj_key_for_reservation(self.PREFIX, reservation_id)
        stored: Dict[str, Any] = json.loads(self.fake_s3.objects[spec_key])
        stored["tools"][0]["instructions"] = "{greet}"
        self.fake_s3.objects[spec_key] = json.dumps(stored).encode("utf-8")

        agent_network: Optional[AgentNetwork]
        _, agent_network = self.storage.reader.get_one_reservation(reservation_id)

        self.assertIsInstance(agent_network, AgentNetwork)
        self.assertEqual("hello", ByokAgentSpecBuilder.front_man_spec(agent_network)["instructions"])
        self.assertNotIn("commondefs", agent_network.get_config())

    def test_get_one_reservation_reports_chain_error_as_absent(self) -> None:
        """
        A commondefs block that is not a dictionary makes the commondefs filter raise;
        the reader must swallow that and report the reservation as absent.
        """
        reservation_id: str = self._put_raw_byok_reservation("byok-bad-commondefs", {"commondefs": "oops"})

        result: Tuple[Optional[Reservation], Optional[AgentNetwork]] = \
            self.storage.reader.get_one_reservation(reservation_id)

        self.assertEqual((None, None), result)

    def test_get_one_reservation_reports_defaults_merge_error_as_absent(self) -> None:
        """
        A global sly_data_schema whose "required" is a string instead of a list makes
        DefaultsConfigFilter's union raise; the same policy applies.
        """
        bad_schema: Dict[str, Any] = {"type": "object", "properties": {}, "required": "llm_config"}
        reservation_id: str = self._put_raw_byok_reservation("byok-bad-required", {"sly_data_schema": bad_schema})
        # The front man must declare its own list-valued "required" for the union to be attempted.
        spec_key: str = S3Util.get_obj_key_for_reservation(self.PREFIX, reservation_id)
        stored: Dict[str, Any] = json.loads(self.fake_s3.objects[spec_key])
        stored["tools"][0]["function"]["sly_data_schema"] = {"type": "object", "required": ["http_headers"]}
        self.fake_s3.objects[spec_key] = json.dumps(stored).encode("utf-8")

        result: Tuple[Optional[Reservation], Optional[AgentNetwork]] = \
            self.storage.reader.get_one_reservation(reservation_id)

        self.assertEqual((None, None), result)

    def test_repeated_reads_reuse_one_client(self) -> None:
        """
        N successful reads of the same reservation should construct
        exactly one S3 client.

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
        one-client-per-read. Under the per-call design this failed with
        create_client called N times (once per read): each read built a client
        under the worker lock and close()d it in a finally block, so nothing was
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
                reservation: Optional[Reservation]
                agent_network: Optional[AgentNetwork]
                reservation, agent_network = self.storage.reader.get_one_reservation(reservation_id)
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

    def test_empty_chain_triggers_retry_and_read_succeeds(self) -> None:
        """
        Scenario: the reader needs a client while the credential chain
        momentarily resolves to None (credentials file mid-rewrite); by
        the retry's second resolution the rewrite has landed.

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
        widening, this test fails with NoCredentialsError propagating out of
        get_one_reservation() after a single resolution.

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
        # See the class docstring for why the partial is wrapped in a MagicMock
        # rather than patched onto Session.get_credentials bare.
        get_credentials = MagicMock(side_effect=partial(self._resolve_chain_mid_rewrite, resolutions))

        # sync_sleep is patched so the retry's jittered backoff does not
        # slow the test down; recovery behavior is unaffected.
        with self._fresh_reader_client(self._create_client_healthy), patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_sync_client_worker.Session.get_credentials",
            new=get_credentials,
        ), patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_sync_client_worker.sync_sleep"
        ):
            reservation: Optional[Reservation]
            agent_network: Optional[AgentNetwork]
            reservation, agent_network = self.storage.reader.get_one_reservation(reservation_id)

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

    @staticmethod
    def _resolve_chain_mid_rewrite(resolutions: Dict[str, int], *_args: Any, **_kwargs: Any) -> Optional[object]:
        """
        Session.get_credentials replacement for test_empty_chain_triggers_retry_and_read_succeeds:
        the first resolution finds the chain empty, every later one finds it healthy.

        :param resolutions: Shared counter dict; its "count" entry is incremented per call
        :param _args: Positional get_credentials arguments, ignored
        :param _kwargs: Keyword get_credentials arguments, ignored
        :return: None on the first call (the rotation's rewrite has the file empty
                right now); afterwards an opaque sentinel standing in for resolved
                credentials, since get_client() only checks "is None"
        """
        resolutions["count"] += 1
        if resolutions["count"] == 1:
            # The rotation's rewrite has the file empty right now.
            return None
        # The rewrite landed; the chain resolves real credentials
        # again. get_client() only checks "is None", so any sentinel
        # models resolved credentials.
        return object()

    def _create_client_healthy(self, *_args: Any, **_kwargs: Any) -> FakeS3Client:
        """
        Session.create_client replacement that always hands back the fake bucket,
        for tests where the client itself is healthy and the failure is injected
        elsewhere (e.g. into the credential chain).

        :param _args: Positional create_client arguments, ignored
        :param _kwargs: Keyword create_client arguments, ignored
        :return: The in-memory FakeS3Client the base class built in setUp
        """
        return self.fake_s3

    def test_invalid_token_triggers_rebuild_and_read_succeeds(self) -> None:
        """
        Scenario: the reader's client was built from a bad credential
        state (e.g. captured mid-rotation), so its first GET fails with
        InvalidToken; the re-resolved credential chain behind the SECOND
        client construction is healthy.

        Verifies that a read hitting InvalidToken rebuilds the session +
        client and succeeds, instead of reporting the reservation as
        not-found until a process restart (the neuro-san-studio #1310
        failure mode; the gate's classification itself is pinned in
        test_s3_util.py).

        Expected: the widened gate routes InvalidToken through the same
        reset-and-retry path as ExpiredToken, so the read returns the
        reservation. If InvalidToken is not gated (the pre-widening
        behavior), the error propagates to the reader's log-and-continue
        handler and this test fails with a (None, None) read after a
        single client construction.
        """
        reservation_id: str = self._put_live_reservation("copy_cat-invalid-token")

        credential_state = {"bad": True}
        creations = {"count": 0}
        # See the class docstring for why the partial is wrapped in a MagicMock
        # rather than patched onto Session.create_client bare.
        create_client = MagicMock(
            side_effect=partial(self._create_client_with_recovery, credential_state, creations))

        # sync_sleep is patched so the retry's jittered backoff does not
        # slow the test down; recovery behavior is unaffected.
        with self._fresh_reader_client(create_client), patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_sync_client_worker.sync_sleep"
        ):
            reservation: Optional[Reservation]
            agent_network: Optional[AgentNetwork]
            reservation, agent_network = self.storage.reader.get_one_reservation(reservation_id)

        self.assertIsNotNone(
            reservation,
            "Expected the read to recover from InvalidToken by rebuilding the "
            "session + client. A None reservation means the error was logged and "
            "swallowed instead - the #1310 failure mode, where the bad credential "
            "state persists and every read of the network reports it not-found.",
        )
        self.assertIsNotNone(agent_network)
        self.assertGreaterEqual(
            creations["count"], 2,
            f"Expected at least 2 client constructions (the failing client plus "
            f"the rebuild after InvalidToken reached the credential-rejection "
            f"gate); got {creations['count']}. A single construction means the "
            f"gate never fired.",
        )

    def _create_client_with_recovery(self, credential_state: Dict[str, bool], creations: Dict[str, int],
                                     *_args: Any, **_kwargs: Any) -> InvalidTokenS3Client:
        """
        Session.create_client replacement for test_invalid_token_triggers_rebuild_and_read_succeeds:
        the first client is built from a bad credential state and rejects every request
        with InvalidToken; from the second construction on the state has healed.

        :param credential_state: Shared dict whose "bad" entry is the credential state
                clients are built from; flipped to False on the second construction
        :param creations: Shared counter dict; its "count" entry is incremented per call
        :param _args: Positional create_client arguments, ignored
        :param _kwargs: Keyword create_client arguments, ignored
        :return: An InvalidTokenS3Client frozen to the credential state at construction
        """
        creations["count"] += 1
        if creations["count"] >= 2:
            # The retry's reset discarded the session; the re-resolved
            # chain behind this second construction is healthy.
            credential_state["bad"] = False
        return InvalidTokenS3Client(self.fake_s3, credential_state["bad"])

    def test_token_rotation_between_reads_causes_no_failed_call(self) -> None:
        """
        Scenario: read once while token-1 is valid; the provider then
        rotates to token-2 (token-1 now rejected by S3, as happens on
        the order of an hour for role/STS tokens); read again.

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
        # See the class docstring for why the partial is wrapped in a MagicMock
        # rather than patched onto Session.create_client bare.
        create_client = MagicMock(side_effect=partial(
            self._create_token_bound_client, provider_state, failed_calls, create_client_kwargs))

        with self._fresh_reader_client(create_client):
            reservation: Optional[Reservation]
            reservation, _ = self.storage.reader.get_one_reservation(reservation_id)
            self.assertIsNotNone(
                reservation,
                "Expected the read under token-1 to succeed (control for this test).",
            )

            # The provider rotates: token-1 is now rejected by S3, and
            # anything that resolves credentials at request time gets
            # valid token-2.
            provider_state["current_token"] = "token-2"

            reservation, _ = self.storage.reader.get_one_reservation(reservation_id)
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
            "_fresh_reader_client()'s reset should have forced one.",
        )
        for kwargs in create_client_kwargs:
            self.assertFalse(
                explicit_key_args & set(kwargs),
                f"Expected the S3 client to be created without explicit credential "
                f"arguments (keyless), but create_client received "
                f"{sorted(explicit_key_args & set(kwargs))}.",
            )

    def _create_token_bound_client(self, provider_state: Dict[str, str], failed_calls: List[Tuple[str, str]],
                                   create_client_kwargs: List[Dict[str, Any]],
                                   *_args: Any, **kwargs: Any) -> TokenBoundS3Client:
        """
        Session.create_client replacement for test_token_rotation_between_reads_causes_no_failed_call:
        records HOW each client was created and hands back a TokenBoundS3Client bound
        the same way.

        If explicit keys were passed, the pinned token is captured exactly as
        create_client(aws_session_token=...) pins it into a static Credentials
        object; a keyless creation leaves it None and the client resolves the
        provider's token per request.

        :param provider_state: Shared dict whose "current_token" entry the test rotates
        :param failed_calls: Shared list the client appends every stale-token request to
        :param create_client_kwargs: Shared list every construction's keyword arguments
                are appended to, for the keyless-creation mechanism check
        :param _args: Positional create_client arguments, ignored
        :param kwargs: Keyword create_client arguments, recorded and inspected for a
                pinned aws_session_token
        :return: A TokenBoundS3Client bound to the token pinned at creation, if any
        """
        create_client_kwargs.append(kwargs)
        return TokenBoundS3Client(
            self.fake_s3, kwargs.get("aws_session_token"), provider_state, failed_calls,
        )
