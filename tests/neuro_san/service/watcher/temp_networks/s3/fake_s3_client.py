
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
import io

from datetime import datetime
from datetime import timezone

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

from botocore.exceptions import ClientError


class FakeS3Client:
    """
    Minimal in-memory stand-in for a boto3 S3 client. Only implements the
    methods that S3ReservationsStorage actually calls, storing object bodies
    in a dict keyed by S3 object key. Method signatures use boto3's PascalCase
    keyword arguments so the storage's call sites work unchanged.

    Pytest's default test-file pattern is test_*.py, so this module (which
    does not start with "test_") is not collected as a test module.
    """

    def __init__(self) -> None:
        """
        Initialize an empty in-memory bucket.
        """
        self.objects: Dict[str, bytes] = {}
        # Per-key LastModified timestamps, surfaced by head_object().
        # put_object() stamps "now"; tests that insert into self.objects
        # directly can backdate a key here to exercise age-based behavior.
        self.last_modified: Dict[str, datetime] = {}

    # pylint: disable=invalid-name
    def head_bucket(self, Bucket: str) -> Dict[str, Any]:
        """
        Stand-in for boto3's head_bucket. Real boto3 returns a response dict
        on success and raises ClientError otherwise. For tests we treat any
        configured bucket as existing.

        :param Bucket: The S3 bucket name (boto3's PascalCase keyword argument)
        :return: An empty response dict, since every bucket is treated as existing
        """
        _ = Bucket
        return {}

    def put_object(self, Bucket: str, Key: str, Body: Union[bytes, str],
                   ContentType: str) -> Dict[str, Any]:
        """
        Store the given Body bytes (or str, encoded as utf-8) at Key.

        :param Bucket: The S3 bucket name (boto3's PascalCase keyword argument)
        :param Key: The S3 object key to store the body under
        :param Body: The object body; a str is utf-8 encoded, matching how the
                writer hands its JSON document to aiobotocore
        :param ContentType: The MIME type the caller declares; ignored by the fake
        :return: An empty response dict, mirroring a successful boto3 put
        """
        _ = Bucket, ContentType
        if isinstance(Body, str):
            Body = Body.encode("utf-8")
        self.objects[Key] = Body
        self.last_modified[Key] = datetime.now(timezone.utc)
        return {}

    def get_object(self, Bucket: str, Key: str) -> Dict[str, Any]:
        """
        Return the stored bytes for Key wrapped in a Body stream, or raise
        a NoSuchKey ClientError if the key is not present.

        :param Bucket: The S3 bucket name (boto3's PascalCase keyword argument)
        :param Key: The S3 object key to fetch
        :return: A response dict whose "Body" is a BytesIO over the stored bytes
        :raises ClientError: NoSuchKey when Key is not in the bucket
        """
        _ = Bucket
        if Key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "Not Found"}},
                "GetObject",
            )
        return {"Body": io.BytesIO(self.objects[Key])}

    def list_objects_v2(self, Bucket: Optional[str] = None, Prefix: str = "",
                        MaxKeys: int = 1000, ContinuationToken: Optional[str] = None) -> Dict[str, Any]:
        """
        Stand-in for boto3's list_objects_v2, backed by the in-memory dict.

        Mirrors the aspects of real S3 the expiration sweep relies on:
          * Keys are returned in lexicographic (UTF-8 binary) order, which is
            what real S3 guarantees. Tests can therefore control the sweep's
            processing order by choosing key names (e.g. "a-poison" sorts
            before "z-expired").
          * When no keys match, the "Contents" key is omitted entirely; real
            S3 omits it for empty result sets rather than returning [].
          * Everything fits in one page (IsTruncated=False). Multi-page
            behavior is exercised separately with a MagicMock side_effect
            (see test_s3_reservations_expiration.py::
            test_iter_reservation_keys_retries_on_throttling_first_page), so this fake does not implement
            ContinuationToken threading.

        :param Bucket: The S3 bucket name (boto3's PascalCase keyword argument)
        :param Prefix: Only keys starting with this prefix are listed
        :param MaxKeys: The page size a real client would honor; ignored by the fake
        :param ContinuationToken: The paging token a real client would honor; ignored by the fake
        :return: A response dict with "IsTruncated" False and, when any key
                matches, a "Contents" list of {"Key": ...} entries in key order
        """
        _ = Bucket, MaxKeys, ContinuationToken
        keys: List[str] = []
        for key in self.objects:
            if key.startswith(Prefix):
                keys.append(key)
        # Real S3 returns keys in UTF-8 binary order; sorting the str keys
        # gives the same order, which the sweep-ordering tests rely on.
        keys.sort()
        response: Dict[str, Any] = {"IsTruncated": False}
        if keys:
            contents: List[Dict[str, str]] = []
            for key in keys:
                contents.append({"Key": key})
            response["Contents"] = contents
        return response

    def delete_object(self, Bucket: str, Key: str) -> Dict[str, Any]:
        """
        Stand-in for boto3's delete_object.

        Real S3 DELETE is idempotent: deleting a key that does not exist
        returns 204 success, NOT a NoSuchKey error. The fake mirrors that so
        tests exercise the storage code against real S3 semantics rather than
        a stricter fake-only contract.

        :param Bucket: The S3 bucket name (boto3's PascalCase keyword argument)
        :param Key: The S3 object key to remove; a missing key is not an error
        :return: An empty response dict, mirroring S3's 204 on DELETE
        """
        _ = Bucket
        self.objects.pop(Key, None)
        self.last_modified.pop(Key, None)
        return {}

    def head_object(self, Bucket: str, Key: str) -> Dict[str, Any]:
        """
        Stand-in for boto3's head_object.

        Keys inserted directly into self.objects (bypassing put_object)
        default to "now", so they read as freshly written unless a test
        backdates them via self.last_modified.

        Real S3 signals a missing key on HEAD with error code "404" (a HEAD
        response has no body to carry a NoSuchKey code), and the fake
        mirrors that.

        :param Bucket: The S3 bucket name (boto3's PascalCase keyword argument)
        :param Key: The S3 object key to describe
        :return: A response dict with the key's "LastModified" datetime and
                "ContentLength" in bytes
        :raises ClientError: Code "404" when Key is not in the bucket
        """
        _ = Bucket
        if Key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}},
                "HeadObject",
            )
        return {
            "LastModified": self.last_modified.get(Key, datetime.now(timezone.utc)),
            "ContentLength": len(self.objects[Key]),
        }
