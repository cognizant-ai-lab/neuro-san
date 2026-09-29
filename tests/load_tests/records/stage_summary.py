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

from typing import Dict
from typing import List
from typing import Optional

from typing_extensions import TypedDict

from tests.load_tests.records.network_token_entry import NetworkTokenEntry
from tests.load_tests.records.request_result import RequestResult
from tests.load_tests.records.status_counts import StatusCounts
from tests.load_tests.records.validation_event import ValidationEvent


class StageSummary(TypedDict, total=False):
    """Aggregate data for a single load test stage.

    All fields are optional because resource monitoring and server
    log parsing are not always enabled.
    """

    stage: int
    round: int
    concurrent: int
    counts: StatusCounts
    elapsed: float
    retries: Dict[str, int]
    total_retries: int
    amplification: float
    results: List[RequestResult]
    primary_started: Optional[int]
    primary_finished: Optional[int]
    total_started: Optional[int]
    total_finished: Optional[int]
    disconnections: List[Dict[str, str]]
    server_errors: List[Dict[str, str]]
    network_tokens: List[NetworkTokenEntry]
    validation_events: List[ValidationEvent]
    has_server_log: bool
    has_tokens: bool
    before_threads: Optional[int]
    after_threads: Optional[int]
    peak_threads: Optional[int]
    before_server_rss: Optional[float]
    after_server_rss: Optional[float]
    peak_server_rss: Optional[float]
    before_client_rss: Optional[float]
    after_client_rss: Optional[float]
    peak_client_rss: Optional[float]
    before_sys_mem_pct: Optional[float]
    after_sys_mem_pct: Optional[float]
    peak_sys_mem_pct: Optional[float]
    before_sys_mem_avail_gb: Optional[float]
    after_sys_mem_avail_gb: Optional[float]
    peak_sys_mem_avail_gb: Optional[float]
    before_sys_cpu: Optional[float]
    after_sys_cpu: Optional[float]
    peak_sys_cpu: Optional[float]
    before_sys_threads: Optional[int]
    after_sys_threads: Optional[int]
    peak_sys_threads: Optional[int]
