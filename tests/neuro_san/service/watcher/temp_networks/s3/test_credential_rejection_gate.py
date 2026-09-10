
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

from unittest import TestCase

from botocore.exceptions import BotoCoreError
from botocore.exceptions import ClientError
from botocore.exceptions import EndpointConnectionError
from botocore.exceptions import NoCredentialsError
from botocore.exceptions import PartialCredentialsError

from neuro_san.service.watcher.temp_networks.s3.s3_util import S3Util


def _make_client_error(code: str, operation_name: str = "GetObject") -> ClientError:
    """
    Build a ClientError carrying the given S3 error code, shaped the way
    boto3 surfaces credential rejections (HTTP 400 with a parsed body code).
    """
    return ClientError(
        {
            "Error": {
                "Code": code,
                "Message": f"{code} (test)",
            },
            "ResponseMetadata": {"HTTPStatusCode": 400},
        },
        operation_name,
    )


class TestCredentialRejectionGate(TestCase):
    """
    Pins recovery from S3 rejecting a request's session token as
    InvalidToken ("The provided token is malformed or otherwise invalid")
    on the reservation READ path.

    Motivation - a real production failure (neuro-san-studio issue #1310,
    "AND is sporadically broken"):

        S3ReservationsReader: S3 error processing reservation object <id>
        during sync: An error occurred (InvalidToken) when calling the
        GetObject operation: The provided token is malformed or otherwise
        invalid.

    The user-visible symptom was a network that had just been created
    coming back "not found": the reader's ClientError handler logged the
    credential error and reported the reservation as missing. Under the
    credential design of that era, the reset gate matched only
    ExpiredToken, so an InvalidToken credential state was never invalidated
    - every cache-miss read kept failing until a pod restart.

    The widened gate (S3Util.is_credential_rejection_error) treats
    InvalidToken like ExpiredToken: discard the session + client,
    re-resolve the credential chain, and retry. Without the widening, the
    recovery test below fails with get_one_reservation() returning
    (None, None) after a single client construction - the exact #1310
    failure mode.
    """

    def test_codes_that_trigger_re_resolution(self):
        """
        Expired, malformed/mismatched, and refresh-required token codes must
        trigger a rebuild: with keyless clients, each can only mean the
        resolved credential state is bad, and re-resolving the chain is the
        only remedy.
        """
        for code in ("ExpiredToken", "ExpiredTokenException", "InvalidToken", "TokenRefreshRequired"):
            with self.subTest(code=code):
                self.assertTrue(
                    S3Util.is_credential_rejection_error(_make_client_error(code)),
                    f"Expected {code} to trigger credential re-resolution.",
                )

    def test_codes_that_must_surface(self):
        """
        Rotated long-lived key pairs and signing problems must NOT be
        retried: re-resolution cannot fix them, and retrying would mask
        genuine misconfiguration behind seconds of doomed backoff.
        """
        for code in ("InvalidAccessKeyId", "SignatureDoesNotMatch", "AccessDenied", "NoSuchKey"):
            with self.subTest(code=code):
                self.assertFalse(
                    S3Util.is_credential_rejection_error(_make_client_error(code)),
                    f"Expected {code} NOT to trigger credential re-resolution.",
                )

    def test_local_resolution_failures_trigger_re_resolution(self):
        """
        NoCredentialsError / PartialCredentialsError are raised locally by
        botocore when the chain resolves empty or half-written (e.g. a
        credentials file caught mid-rewrite). They are BotoCoreErrors, not
        ClientErrors, and must classify as credential rejections so the
        workers' retry loops - which catch them alongside ClientError -
        ride out the rewrite instead of failing the read or losing the
        write batch.
        """
        self.assertTrue(S3Util.is_credential_rejection_error(NoCredentialsError()))
        self.assertTrue(S3Util.is_credential_rejection_error(
            PartialCredentialsError(provider="shared-credentials-file",
                                    cred_var="aws_secret_access_key")))

    def test_other_local_errors_must_surface(self):
        """
        Generic BotoCoreErrors (network trouble, endpoint problems) are not
        credential rejections: re-resolving the chain cannot fix them, so
        they must surface to their own (transient-retry or fail) handling.
        """
        self.assertFalse(S3Util.is_credential_rejection_error(BotoCoreError()))
        self.assertFalse(S3Util.is_credential_rejection_error(
            EndpointConnectionError(endpoint_url="https://s3.us-east-1.amazonaws.com")))
