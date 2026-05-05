
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
S3ReservationsStorage commits to a specific on-disk format for every
reservation it writes:
  - Serialization is JSON (we chose json.dumps, not pickle/yaml/proto).
  - The original agent_spec lives at the top level of the document
    (no wrap-in-envelope like {"data": ...}).
  - Storage-injected bookkeeping fields live under a "metadata" key
    ("reservation" with the serialized Reservation, "stored_at" with
    the wall-clock timestamp).

External consumers (CLI tools, dashboards, debugging operators) read
these objects directly and rely on the format being stable. T1's
round-trip would still pass if the read+write paths were updated
together but the on-disk format silently changed; this module pins
the format by reading the raw bytes and asserting on the parsed
shape, independent of the storage's read path.

Encoding/line-ending properties (UTF-8, no BOM, no CRLF) are
boto3+Python concerns and are intentionally NOT tested here.
"""
from json import loads

from tests.neuro_san.service.watcher.temp_networks._test_base \
    import S3ReservationsStorageTestBase


class TestJsonBodyFormat(S3ReservationsStorageTestBase):
    """
    Pin the on-disk JSON shape produced by add_reservations. Reads
    the raw bytes from the FakeS3Client and asserts on the parsed
    structure, independent of the storage's read path.
    """

    def test_add_writes_json_body_with_expected_top_level_shape(self):
        """
        After add_reservations, the S3 object body should:
          - Decode as a JSON object (we chose JSON over
            pickle/yaml/proto).
          - Carry the original agent_spec fields at the top level
            (no wrap-in-envelope).
          - Carry the storage-injected reservation+stored_at under
            "metadata".

        Catches regressions in our serialization choice: a switch
        to a different format, an outer envelope refactor, dropped
        or relocated metadata fields, or a wrong reservation id
        under metadata.
        """
        reservation_id = "copy_cat-test-UUID-0012"
        reservation = self._make_reservation(reservation_id, lifetime_seconds=600.0)
        agent_spec = self._make_agent_spec("copy_cat")

        self.storage.add_reservations({reservation: agent_spec})

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

        # Parses as a JSON object. Catches a switch in our
        # serialization choice (pickle, yaml, protobuf) - all of
        # which would either raise or yield a non-dict here.
        parsed = loads(body)
        self.assertIsInstance(
            parsed,
            dict,
            f"On-disk body parsed but the top-level value is not a "
            f"dict; got {type(parsed).__name__}.",
        )

        # Original agent_spec fields are preserved at the top level.
        # Catches a wrap-in-envelope refactor (e.g.,
        # {"data": agent_spec}) and field-renaming refactors that
        # would relocate the spec under a different key.
        self.assertEqual(
            "copy_cat",
            parsed.get("name"),
            f"Top-level 'name' missing or wrong; parsed top-level "
            f"keys: {list(parsed)}.",
        )
        self.assertIn(
            "llm_config",
            parsed,
            f"Top-level 'llm_config' missing; parsed top-level "
            f"keys: {list(parsed)}.",
        )
        self.assertIn(
            "tools",
            parsed,
            f"Top-level 'tools' missing; parsed top-level keys: "
            f"{list(parsed)}.",
        )

        # Storage-injected metadata is at the documented path.
        # Catches a regression where the bookkeeping fields are
        # dropped, relocated to the top level, or written under a
        # differently-named key (e.g., "info" instead of
        # "metadata").
        self.assertIn(
            "metadata",
            parsed,
            f"On-disk JSON has no 'metadata' key; parsed top-level "
            f"keys: {list(parsed)}.",
        )
        metadata = parsed["metadata"]
        self.assertIn(
            "reservation",
            metadata,
            f"metadata['reservation'] missing; metadata keys: "
            f"{list(metadata)}.",
        )
        self.assertIn(
            "stored_at",
            metadata,
            f"metadata['stored_at'] missing; metadata keys: "
            f"{list(metadata)}.",
        )

        # The reservation id under metadata matches what we wrote.
        # Catches regressions where the wrong reservation is
        # serialized into the body or the id field is renamed.
        self.assertEqual(
            reservation_id,
            metadata["reservation"].get("id"),
            f"On-disk metadata.reservation.id does not match the "
            f"written reservation id; metadata.reservation: "
            f"{metadata['reservation']}.",
        )
