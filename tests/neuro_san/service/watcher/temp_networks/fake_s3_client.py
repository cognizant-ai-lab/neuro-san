
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
In-memory stand-in for a boto3 S3 client used by the
S3ReservationsStorage unit tests. Implements only the methods
the storage actually calls, storing object bodies in a dict
keyed by S3 object key. Method signatures use boto3's
PascalCase keyword arguments so the storage's call sites work
unchanged.

Pytest's default test-file pattern is test_*.py, so this file
(which does not start with "test_") is not collected as a test
module.
"""
import io

from typing import Dict

from botocore.exceptions import ClientError


# pylint: disable=invalid-name,unused-argument
class FakeS3Client:
    """
    Minimal in-memory stand-in for a boto3 S3 client. Only implements the
    methods that S3ReservationsStorage actually calls, storing object bodies
    in a dict keyed by S3 object key. Method signatures use boto3's PascalCase
    keyword arguments so the storage's call sites work unchanged.
    """

    def __init__(self):
        """
        Initialize an empty in-memory bucket.
        """
        self.objects: Dict[str, bytes] = {}

    def head_bucket(self, Bucket: str):
        """
        Stand-in for boto3's head_bucket. Real boto3 returns a response dict
        on success and raises ClientError otherwise. For tests we treat any
        configured bucket as existing.
        """
        return {}

    def put_object(self, Bucket: str, Key: str, Body, ContentType: str):
        """
        Store the given Body bytes (or str, encoded as utf-8) at Key.
        """
        if isinstance(Body, str):
            Body = Body.encode("utf-8")
        self.objects[Key] = Body
        return {}

    def get_object(self, Bucket: str, Key: str):
        """
        Return the stored bytes for Key wrapped in a Body stream, or raise
        a NoSuchKey ClientError if the key is not present.
        """
        if Key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "Not Found"}},
                "GetObject",
            )
        return {"Body": io.BytesIO(self.objects[Key])}
