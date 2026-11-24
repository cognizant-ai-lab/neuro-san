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

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from openai import RateLimitError

from neuro_san.internals.run_context.langchain.core.run_context_runnable import RunContextRunnable
from tests.neuro_san.internals.run_context.langchain.core.run_context_runnable_test_helpers import \
    RunContextRunnableTestHelpers


class TestRunContextRunnableBackoff(IsolatedAsyncioTestCase):
    """
    Unit tests for model call jittered backoff, server retry hints extraction, and retry delays in RunContextRunnable.
    """

    def setUp(self) -> None:
        """
        Isolate tests from real backoff sleep delays.
        """
        self.original_do_sleep: Any = RunContextRunnable.do_sleep
        sleep_patcher: Any = patch.object(RunContextRunnable, "do_sleep", new_callable=AsyncMock)
        self.mock_do_sleep: AsyncMock = sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)

    def test_parse_duration_seconds(self) -> None:
        """
        parse_duration_seconds correctly handles floats, integers, duration strings, and invalid inputs.
        """
        self.assertEqual(4.15, RunContextRunnable.parse_duration_seconds(4.15))
        self.assertEqual(10.0, RunContextRunnable.parse_duration_seconds(10))
        self.assertEqual(4.15, RunContextRunnable.parse_duration_seconds("4.15s"))
        self.assertEqual(26.0, RunContextRunnable.parse_duration_seconds("26s"))
        self.assertEqual(10.5, RunContextRunnable.parse_duration_seconds(" 10.5 "))
        self.assertIsNone(RunContextRunnable.parse_duration_seconds(True))
        self.assertIsNone(RunContextRunnable.parse_duration_seconds("invalid"))
        self.assertIsNone(RunContextRunnable.parse_duration_seconds(None))

    def test_extract_server_retry_delay_from_structured_details(self) -> None:
        """
        extract_server_retry_delay extracts retryDelay from structured exception details.
        """
        error: Exception = Exception("Rate limit exceeded")
        error.details = {
            "error": {
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "5.5s"
                    }
                ]
            }
        }
        delay: Optional[float] = RunContextRunnable.extract_server_retry_delay(error)
        self.assertEqual(5.5, delay)

    def test_extract_server_retry_delay_from_response_headers(self) -> None:
        """
        extract_server_retry_delay extracts retry delay from Retry-After response headers.
        """
        error: Exception = Exception("Too Many Requests")
        mock_response: MagicMock = MagicMock()
        mock_response.headers = {"Retry-After": "15.0"}
        error.response = mock_response

        delay: Optional[float] = RunContextRunnable.extract_server_retry_delay(error)
        self.assertEqual(15.0, delay)

    def test_extract_server_retry_delay_from_regex_text(self) -> None:
        """
        extract_server_retry_delay extracts retry delay from error text using regex patterns.
        """
        error_with_in: Exception = Exception("Resource exhausted: please retry in 4.15s")
        self.assertEqual(4.15, RunContextRunnable.extract_server_retry_delay(error_with_in))

        error_with_after: Exception = Exception("Rate limit reached. Please retry after 20 seconds.")
        self.assertEqual(20.0, RunContextRunnable.extract_server_retry_delay(error_with_after))

        error_with_wait: Exception = Exception("High demand. Please wait for 3.5s")
        self.assertEqual(3.5, RunContextRunnable.extract_server_retry_delay(error_with_wait))

        unrelated_error: Exception = Exception("Network connection lost")
        self.assertIsNone(RunContextRunnable.extract_server_retry_delay(unrelated_error))
        self.assertIsNone(RunContextRunnable.extract_server_retry_delay(None))

    def test_calculate_backoff_delay_with_server_hint(self) -> None:
        """
        calculate_backoff_delay honors provider-suggested delay with safety jitter and caps at quota cap.
        """
        error: Exception = Exception("Please retry in 8.0s")
        delay: float = RunContextRunnable.calculate_backoff_delay(0, error)
        self.assertGreaterEqual(delay, 8.5)
        self.assertLessEqual(delay, 10.0)

        huge_error: Exception = Exception("Please retry in 1000s")
        capped_delay: float = RunContextRunnable.calculate_backoff_delay(0, huge_error)
        self.assertEqual(60.0, capped_delay)

    def test_calculate_backoff_delay_exponential_with_jitter(self) -> None:
        """
        calculate_backoff_delay without hints returns exponential backoff with full jitter.
        """
        # Attempt 0: raw is base_delay (1.0), result in [0.0, 1.0]
        delay_0: float = RunContextRunnable.calculate_backoff_delay(0)
        self.assertGreaterEqual(delay_0, 0.0)
        self.assertLessEqual(delay_0, 1.0)

        # Attempt 3: raw is 1.0 * 2^3 = 8.0, result in [0.0, 8.0]
        delay_3: float = RunContextRunnable.calculate_backoff_delay(3)
        self.assertGreaterEqual(delay_3, 0.0)
        self.assertLessEqual(delay_3, 8.0)

        # Attempt 10: raw is 1024.0, capped at max_delay (60.0)
        delay_10: float = RunContextRunnable.calculate_backoff_delay(10)
        self.assertGreaterEqual(delay_10, 0.0)
        self.assertLessEqual(delay_10, 60.0)

    async def test_sleep_before_retry_calls_do_sleep(self) -> None:
        """
        sleep_before_retry computes the delay and awaits do_sleep.
        """
        runnable: RunContextRunnable = RunContextRunnableTestHelpers.make_runnable()
        error: Exception = Exception("Please retry in 5.0s")
        await runnable.sleep_before_retry(0, error)

        self.mock_do_sleep.assert_awaited_once()
        awaited_delay: float = self.mock_do_sleep.call_args[0][0]
        self.assertGreaterEqual(awaited_delay, 5.5)
        self.assertLessEqual(awaited_delay, 7.0)

    async def test_invoke_agent_chain_calls_sleep_before_retry_on_recoverable_error(self) -> None:
        """
        invoke_agent_chain sleeps before retrying when a recoverable rate limit error occurs.
        """
        journal: MagicMock = MagicMock()
        journal.write_message = AsyncMock()
        sensitive_logger: MagicMock = MagicMock()
        runnable: RunContextRunnable = RunContextRunnable.model_construct(
            journal=journal,
            sensitive_logger=sensitive_logger,
            error_detector=MagicMock(handle_error=RunContextRunnableTestHelpers.passthrough),
            chat_history=None
        )
        rate_error: RateLimitError = RateLimitError(
            message="Please retry in 3.0s",
            response=MagicMock(status_code=429, headers={}),
            body=None
        )
        successful_state: Dict[str, Any] = {"output": "Recovered successfully"}
        run_chain_mock: AsyncMock = AsyncMock(side_effect=[rate_error, successful_state])

        with patch.object(RunContextRunnable, "run_chain", new=run_chain_mock):
            with patch.object(RunContextRunnable, "sleep_before_retry", new_callable=AsyncMock) as mock_sleep:
                await runnable.invoke_agent_chain(inputs={"input": "test"}, runnable_config={}, max_attempts=2)
                mock_sleep.assert_awaited_once_with(0, rate_error)

    async def test_do_sleep_awaits_asyncio_sleep(self) -> None:
        """
        do_sleep calls asyncio.sleep with the provided delay.
        """
        runnable: RunContextRunnable = RunContextRunnableTestHelpers.make_runnable()
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_asyncio_sleep:
            await self.original_do_sleep(runnable, 2.5)
            mock_asyncio_sleep.assert_awaited_once_with(2.5)

    def test_extract_server_retry_delay_with_malformed_structures(self) -> None:
        """
        extract_server_retry_delay safely handles malformed details and response headers.
        """
        error_non_dict_error: Exception = Exception("Failed")
        error_non_dict_error.details = {"error": "not-a-dict"}
        self.assertIsNone(RunContextRunnable.extract_server_retry_delay(error_non_dict_error))

        error_non_list_details: Exception = Exception("Failed")
        error_non_list_details.details = {"error": {"details": "not-a-list"}}
        self.assertIsNone(RunContextRunnable.extract_server_retry_delay(error_non_list_details))

        error_missing_retry_delay: Exception = Exception("Failed")
        error_missing_retry_delay.details = {"error": {"details": [{"code": 429}]}}
        self.assertIsNone(RunContextRunnable.extract_server_retry_delay(error_missing_retry_delay))

        error_non_dict_headers: Exception = Exception("Failed")
        mock_response_bad_headers: MagicMock = MagicMock()
        mock_response_bad_headers.headers = "not-a-dict"
        error_non_dict_headers.response = mock_response_bad_headers
        self.assertIsNone(RunContextRunnable.extract_server_retry_delay(error_non_dict_headers))

        error_unrelated_headers: Exception = Exception("Failed")
        mock_response_other: MagicMock = MagicMock()
        mock_response_other.headers = {"content-type": "application/json"}
        error_unrelated_headers.response = mock_response_other
        self.assertIsNone(RunContextRunnable.extract_server_retry_delay(error_unrelated_headers))

    def test_extract_server_retry_delay_from_lowercase_retry_after_header(self) -> None:
        """
        extract_server_retry_delay extracts retry delay from lowercase retry-after response headers.
        """
        error: Exception = Exception("Too Many Requests")
        mock_response: MagicMock = MagicMock()
        mock_response.headers = {"retry-after": "18.5"}
        error.response = mock_response

        delay: Optional[float] = RunContextRunnable.extract_server_retry_delay(error)
        self.assertEqual(18.5, delay)

    async def test_sleep_before_retry_skips_when_delay_is_zero(self) -> None:
        """
        sleep_before_retry does not call do_sleep if delay is zero.
        """
        runnable: RunContextRunnable = RunContextRunnableTestHelpers.make_runnable()
        with patch.object(RunContextRunnable, "calculate_backoff_delay", return_value=0.0):
            await runnable.sleep_before_retry(0, None)
            self.mock_do_sleep.assert_not_awaited()

    async def test_sleep_before_retry_logs_with_sensitive_logger(self) -> None:
        """
        sleep_before_retry logs info message when sensitive_logger is present.
        """
        runnable: RunContextRunnable = RunContextRunnableTestHelpers.make_runnable()
        runnable.sensitive_logger = MagicMock()
        with patch.object(RunContextRunnable, "calculate_backoff_delay", return_value=1.5):
            await runnable.sleep_before_retry(2, None)
            self.mock_do_sleep.assert_awaited_once_with(1.5)
            runnable.sensitive_logger.info.assert_called_once()
            call_args: Any = runnable.sensitive_logger.info.call_args[0]
            self.assertIn("Backing off for", call_args[0])
            self.assertEqual(1.5, call_args[1])
            self.assertEqual(3, call_args[2])
