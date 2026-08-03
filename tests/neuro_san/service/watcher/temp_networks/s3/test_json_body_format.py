
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
the format by reading the raw bytes and validating the parsed
document against a JSON Schema, independent of the storage's read
path.

Encoding/line-ending properties (UTF-8, no BOM, no CRLF) are
boto3+Python concerns and are intentionally NOT tested here.
"""
from json import loads
import pytest

from jsonschema import validate

from tests.neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


# Documents the on-disk JSON shape that S3ReservationsStorage commits
# to. The schema is the single source of truth for the format and is
# what external consumers (CLI tools, dashboards, debug operators) can
# rely on. Any future test that needs to pin the same shape can reuse
# this constant.
RESERVATION_OBJECT_SCHEMA = {
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


class TestJsonBodyFormat(S3ReservationsStorageTestBase):
    """
    Pin the on-disk JSON shape produced by add_reservations. Reads
    the raw bytes from the FakeS3Client and validates the parsed
    document against RESERVATION_OBJECT_SCHEMA, independent of the
    storage's read path.
    """

    @pytest.mark.asyncio
    async def test_add_writes_json_body_with_expected_top_level_shape(self):
        """
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
        validate(instance=parsed, schema=RESERVATION_OBJECT_SCHEMA)

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
