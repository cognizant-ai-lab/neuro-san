
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

from typing import Any
from typing import Dict
from typing import Optional

from random import random

from botocore.exceptions import ClientError

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor


class S3Util:
    """
    Utilities for AWS S3 operations.
    """

    DEFAULT_RESERVATIONS_PREFIX: str = "reservations/"

    @staticmethod
    def is_retryable_client_error(err: ClientError) -> bool:
        """
        Determine if a ClientError is worth retrying based on its error code and HTTP status.
        :param err: The ClientError exception to evaluate
        :return: True if the error is likely transient and worth retrying, False otherwise
        """
        extractor = DictionaryExtractor(err.response)
        code = extractor.get("Error.Code", "")
        status = extractor.get("ResponseMetadata.HTTPStatusCode", 0)

        # Common codes for transient situations
        retryable_codes = {
            "SlowDown",
            "Throttling",
            "ThrottlingException",
            "RequestTimeout",
            "RequestTimeoutException",
            "InternalError",
            "ServiceUnavailable",
            "503",
        }
        if code in retryable_codes:
            return True
        # Retry on some 5xx
        if isinstance(status, int) and 500 <= status < 600:
            return True
        return False

    @staticmethod
    def get_error_code(err: ClientError) -> str:
        """
        Safely extract the Error.Code from a botocore ClientError response.

        Why this exists: DictionaryExtractor.get() only applies its default when
        a key is *missing* along the path. When the terminal key is present with
        a stored value of None, that None is returned in preference to the
        default. botocore's REST-XML parser can produce exactly that for S3
        error bodies with an empty <Code/> element (and S3-compatible
        endpoints/test doubles can too), so code like
            "ExpiredToken" not in extractor.get("Error.Code", "")
        raises TypeError ("argument of type 'NoneType' is not iterable") inside
        an exception handler, replacing the real S3 error with a TypeError.
        This helper guarantees a str so substring/equality checks are safe.

        :param err: The ClientError exception to evaluate
        :return: The error code as a string, or "" if it cannot be determined
        """
        extractor = DictionaryExtractor(err.response)
        code: Any = extractor.get("Error.Code", "")
        if not isinstance(code, str):
            code = "" if code is None else str(code)
        return code

    @staticmethod
    def is_expired_token_error(err: ClientError) -> bool:
        """
        :param err: The ClientError exception to evaluate
        :return: True if the error indicates expired credentials.
                 Substring match intentionally covers both "ExpiredToken" and
                 "ExpiredTokenException" (different AWS services/paths use both).
        """
        return "ExpiredToken" in S3Util.get_error_code(err)

    @staticmethod
    def is_credential_rejection_error(err: ClientError) -> bool:
        """
        :param err: The ClientError exception to evaluate
        :return: True if S3 rejected the credentials the request was signed
                 with, in a way that discarding the Session + client and
                 re-resolving the credential chain can plausibly fix:

                 * ExpiredToken / ExpiredTokenException - the session token
                   has expired. For keyless clients this stays dormant for
                   role/SSO sources (they refresh at signing time) and fires
                   for static session tokens rotated externally.
                 * InvalidToken - "malformed or otherwise invalid": the token
                   S3 received does not hang together, e.g. a credential
                   state captured mid-rotation or a revoked role session.
                   Clients are created WITHOUT explicit keys, so our code
                   never assembles a key/secret/token triple itself - this
                   code can only mean the resolved credential state is bad,
                   and re-resolution is the only remedy. Observed in
                   production (neuro-san-studio issue #1310): an InvalidToken
                   state persisted across reads precisely because the
                   previous design's reset gate matched only ExpiredToken.
                   Exact match on purpose; there is no InvalidTokenException
                   variant for S3, and near-misses like InvalidClientTokenId
                   belong to other services.

                 Deliberately NOT matched: InvalidAccessKeyId and
                 SignatureDoesNotMatch. Those indicate rotated long-lived
                 key pairs or genuine signing bugs - retrying would mask
                 real misconfiguration (see the workers' retry docstrings).
        """
        return S3Util.is_expired_token_error(err) or S3Util.get_error_code(err) == "InvalidToken"

    @staticmethod
    def extract_reservation_data(agent_spec: Any) -> Optional[Dict[str, Any]]:
        """
        Single, shared policy point for parsing the reservation block out of an
        agent-spec object read back from S3.

        Before this helper, each consumer had its own ad-hoc handling of
        malformed content, and the policies contradicted each other:
          * S3ReservationsReader defaulted to {} and built a bogus Reservation
            (id=None, expiration=None) whose expiration=None later crashed
            request handling with "'>' not supported between float and NoneType".
          * S3ReservationsExpiration defaulted expiration_time to 0, which made
            "malformed" indistinguishable from "expired at epoch" and silently
            DELETED the object.
        Centralizing the shape check means both consumers agree on what a
        well-formed reservation looks like; each caller decides what a None
        return means for it (reader: treat as not-found; expiration:
        age-gated handling - skip and warn while the object is young, delete
        once it is older than any reservation could live; see
        S3ReservationsExpiration.handle_malformed_object for that policy).

        Note on DictionaryExtractor semantics: its .get() only applies the
        default when a key is missing. A stored JSON null (e.g.
        {"metadata": {"reservation": null}}) is returned as None in preference
        to the default - that exact shape still crashed the expiration sweep
        with "'NoneType' object has no attribute 'get'" even after
        DictionaryExtractor was introduced. That is why the isinstance checks
        below cannot be replaced with extractor defaults.

        :param agent_spec: Whatever was parsed from the S3 object body. May be
                           None or any JSON type, not just a dict.
        :return: The metadata.reservation dict - guaranteed to be a dict with a
                 numeric expiration_time_in_seconds - or None if the object is
                 not shaped like a reservation. The "id" field is intentionally
                 NOT required: it is only used for logging, and requiring it
                 would strand legacy objects that lack one.
        """
        if not isinstance(agent_spec, dict):
            return None

        extractor = DictionaryExtractor(agent_spec)
        reservation_data: Any = extractor.get("metadata.reservation")
        if not isinstance(reservation_data, dict):
            return None

        expiration_time: Any = reservation_data.get("expiration_time_in_seconds")
        # bool is an int subclass in Python; a JSON true/false here is
        # malformed data, not a timestamp, so exclude it explicitly.
        # A stored JSON null (None) also fails the isinstance check below,
        # so a null expiration is treated as malformed here rather than ever
        # reaching a caller's "current_time > expiration_time" comparison as
        # a None (which would raise TypeError).
        if isinstance(expiration_time, bool) or not isinstance(expiration_time, (int, float)):
            return None

        return reservation_data

    @staticmethod
    def exponential_backoff_with_jitter(base_sleep: float, attempt: int) -> float:
        """
        Compute exponential backoff with jitter
        :param base_sleep: base sleep time
        :param attempt: attempt number
        :return: sleep time as float
        """
        sleep: float = base_sleep * (2 ** (attempt - 1))
        sleep = sleep * (0.5 + random())  # sleep time jitter
        return sleep

    @staticmethod
    def get_obj_key_for_reservation(prefix: str, reservation_id: str) -> str:
        """
        Helper method to construct the S3 object key for a given reservation ID.
        :param prefix: The path prefix in the S3 bucket
        :param reservation_id: The ID of the reservation
        :return: The corresponding S3 object key
        """
        return f"{prefix}{reservation_id}.json"
