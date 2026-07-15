
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
Constructor-validation tests for LocalReservationsStorage.

Verifies that the base_path can come from the constructor argument or the
AGENT_RESERVATIONS_LOCAL_PATH environment variable, and that missing both
raises ValueError.
"""
import pytest

from neuro_san.service.watcher.temp_networks.local_reservations_storage import LocalReservationsStorage


class TestLocalReservationsStorageConstructor:
    """
    Constructor validation: path can come from the base_path arg or the
    AGENT_RESERVATIONS_LOCAL_PATH env var; missing both is an error.
    """

    def test_missing_path_raises(self, monkeypatch):
        """No base_path arg and no env var -> ValueError."""
        monkeypatch.delenv("AGENT_RESERVATIONS_LOCAL_PATH", raising=False)
        with pytest.raises(ValueError, match="Local path for reservations"):
            LocalReservationsStorage()

    def test_env_var_fallback(self, monkeypatch, tmp_path):
        """base_path defaults from the env var when the arg is empty."""
        monkeypatch.setenv("AGENT_RESERVATIONS_LOCAL_PATH", str(tmp_path))
        storage = LocalReservationsStorage()
        assert storage.base_path == str(tmp_path.resolve())

    def test_explicit_arg_wins_over_env(self, monkeypatch, tmp_path):
        """A non-empty base_path arg is used even when the env var is set."""
        monkeypatch.setenv("AGENT_RESERVATIONS_LOCAL_PATH", "/some/env/path")
        storage = LocalReservationsStorage(base_path=str(tmp_path))
        assert storage.base_path == str(tmp_path.resolve())
