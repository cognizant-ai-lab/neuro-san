
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
start() lifecycle tests for LocalReservationsStorage.

Verifies that start() creates the storage directory if it does not exist
and is idempotent against an existing directory.
"""
from neuro_san.service.watcher.temp_networks.local.local_reservations_storage import LocalReservationsStorage


class TestLocalReservationsStorageStart:
    """start() creates the storage directory if it does not exist."""

    def test_start_creates_missing_directory(self, tmp_path):
        """start() creates the base directory when it does not yet exist."""
        target = tmp_path / "reservations_dir_that_does_not_exist_yet"
        assert not target.exists()
        LocalReservationsStorage(base_path=str(target)).start()
        assert target.is_dir()

    def test_start_is_idempotent_on_existing_directory(self, tmp_path):
        """start() must not fail when the base directory already exists."""
        target = tmp_path / "already_there"
        target.mkdir()
        LocalReservationsStorage(base_path=str(target)).start()
        assert target.is_dir()
